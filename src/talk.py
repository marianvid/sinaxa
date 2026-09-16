"""Conversation orchestration for one project session."""

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .model import ModelError

PREAMBLE = """You are {name}, occupying the {role} seat in project {project}.
This conversation is the session {session}. The human lead is {lead}.
Participants: {participants}.

Communication between participants is mediated by this transcript. To ask
another participant to answer, address them as @Name. Do not use provider-native
agent messaging or agent-discovery tools for Sinaxa participants. A message
without a mention from the human lead is for the whole session. If you were not
mentioned, respond only when you can add material value; otherwise answer with
exactly [NO_REPLY]. If you mention another participant, you are explicitly
requesting another turn from them. Be conversational and concise unless the
lead asks for a detailed artifact.

Seat instructions:
{prompt}"""


class Conversation:
    def __init__(self, seat_id):
        self.seat_id = seat_id
        self.agent = None
        self.delivered = 0
        self.trouble = None


class Talk:
    def __init__(self, sinaxa, store, project, session, engines):
        self.sinaxa = sinaxa
        self.store = store
        self.project = project
        self.session = session
        self.engines = engines
        self.conversations = {}
        self.busy = set()
        self._lock = threading.RLock()
        self._post_lock = threading.RLock()
        self._round_lock = threading.Lock()

    def conversation(self, seat):
        with self._lock:
            return self.conversations.setdefault(seat.id, Conversation(seat.id))

    def participants(self):
        return [self.project.seat(seat_id)
                for seat_id in self.session.participants]

    def instructions_for(self, seat):
        lead = self.sinaxa.lead
        return PREAMBLE.format(
            name=self.sinaxa.seat_name(self.project, seat), role=seat.role,
            project=self.project.name, session=self.session.name,
            lead=lead.name if lead else "the human lead",
            participants=", ".join(
                "%s (%s)" % (self.sinaxa.seat_name(self.project, one), one.role)
                for one in self.participants()), prompt=seat.prompt)

    def start(self, seat):
        conversation = self.conversation(seat)
        trouble = self.sinaxa.seat_trouble(self.project, seat)
        if trouble:
            conversation.trouble = trouble
            return None
        if conversation.agent is None:
            checkpoint = self.store.checkpoints(self.project, self.session).get(
                seat.id, {})
            member = self.sinaxa.member(seat.occupant)
            conversation.agent = self.engines.agent(
                member, self.sinaxa.seat_name(self.project, seat),
                self.instructions_for(seat), native_id=checkpoint.get("native_id"))
            if checkpoint.get("native_id") and getattr(
                    conversation.agent, "resumed", False):
                conversation.delivered = int(checkpoint.get("delivered", 0))
            conversation.trouble = None
        return conversation.agent

    def stop(self):
        for conversation in self.conversations.values():
            if conversation.agent:
                try:
                    conversation.agent.stop()
                except Exception:
                    pass
                conversation.agent = None

    def clear_context(self):
        """Start a new context epoch while keeping the visible transcript."""
        with self._lock:
            for conversation in self.conversations.values():
                if conversation.agent:
                    conversation.agent.stop()
            self.conversations.clear()
            self.store.clear_checkpoints(self.project, self.session)
            self.session.context_start_seq = self.session.seq + 1
            self.store.save_project(self.project)
            return self.post("Context cleared", author="system", kind="boundary")

    def line(self, message, carried=True):
        count = len(message.get("images", []))
        note = ""
        if count:
            note = " [%d image%s %s]" % (
                count, "" if count == 1 else "s",
                "attached" if carried else "not supported by this engine")
        return "[%s] %s: %s%s" % (self.session.name,
                                   message.get("author_name", "?"),
                                   message.get("text", ""), note)

    def context_for(self, seat, through):
        conversation = self.conversation(seat)
        return [message for message in self.store.messages(self.project, self.session)
                if self.session.context_start_seq <= message.get("seq", 0) <= through
                and message.get("seq", 0) > conversation.delivered
                and message.get("kind") != "boundary"]

    def deliver(self, seat, message, required=False):
        agent = self.start(seat)
        if not agent:
            return None, {"error": self.conversation(seat).trouble}
        carried = bool(getattr(agent, "accepts_images", False))
        batch = self.context_for(seat, message["seq"])
        paths = []
        for item in batch:
            if carried:
                paths.extend(self.store.image_paths(self.project, self.session, item))
        routing = ("[Sinaxa routing] You were explicitly @mentioned and must "
                   "answer." if required else
                   "[Sinaxa routing] You were not explicitly mentioned. "
                   "Answer only if relevant; otherwise return [NO_REPLY].")
        prompt = "\n".join(self.line(item, carried) for item in batch)
        prompt = "%s\n\n%s" % (prompt, routing)
        answer, meta = agent.ask(prompt, timeout=self.session.turn_timeout,
                                 images=paths)
        conversation = self.conversation(seat)
        # A queued mention can become stale after a newer transcript batch was
        # delivered. Never move the cursor backwards in that case.
        conversation.delivered = max(conversation.delivered, message["seq"])
        native_id = agent.native_id() if hasattr(agent, "native_id") else None
        self.store.save_checkpoint(self.project, self.session, seat.id, {
            "native_id": native_id, "delivered": conversation.delivered,
            "engine": self.sinaxa.member(seat.occupant).engine})
        return answer, meta or {}

    def speakers_for(self, text, author_seat=None):
        seats = [seat for seat in self.participants()
                 if seat.id != author_seat
                 and self.sinaxa.seat_runs_engine(seat)]
        if author_seat is None:
            return seats
        return self.sinaxa.mentioned(self.project, text, seats)

    def post(self, text, author="lead", author_name=None, kind=None,
             images=None, meta=None):
        with self._post_lock:
            self.session.seq += 1
            now = time.time()
            self.session.last_activity_at = now
            message = {"seq": self.session.seq, "author": author,
                       "author_name": author_name or (
                           self.sinaxa.lead.name if self.sinaxa.lead else "You"),
                       "text": text, "ts": now}
            if kind:
                message["kind"] = kind
            if images:
                message["images"] = list(images)
            if meta:
                message["meta"] = meta
            self.store.append(self.project, self.session, message)
            self.store.save_project(self.project)
            return message

    def run_turn(self, message, author_seat=None, hops=None, targets=None):
        del hops  # retained for callers from the pre-round scheduler API
        with self._round_lock:
            participants = [seat for seat in self.participants()
                            if self.sinaxa.seat_runs_engine(seat)]
            initial = targets if targets is not None else self.speakers_for(
                message["text"], author_seat)
            explicitly_mentioned = {seat.id for seat in self.sinaxa.mentioned(
                self.project, message["text"], participants)}
            pending = {}
            active_by_seat = {}
            future_meta = {}
            turns = 0
            limit = self.session.max_agent_turns

            def enqueue(seat, through, required):
                conversation = self.conversation(seat)
                if conversation.delivered >= through["seq"]:
                    return
                queued = pending.get(seat.id)
                if not queued or through["seq"] > queued[1]["seq"]:
                    pending[seat.id] = (seat, through, required)
                elif required:
                    pending[seat.id] = (queued[0], queued[1], True)

            for seat in initial:
                enqueue(seat, message, seat.id in explicitly_mentioned)

            workers = max(1, len(participants))
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix="sinaxa-agent") as pool:
                while pending or future_meta:
                    for seat_id in list(pending):
                        if turns >= limit:
                            break
                        if seat_id in active_by_seat:
                            continue
                        seat, through, required = pending.pop(seat_id)
                        self.busy.add(seat.id)
                        future = pool.submit(self.deliver, seat, through, required)
                        active_by_seat[seat.id] = future
                        future_meta[future] = (seat, through)
                        turns += 1

                    if not future_meta:
                        break
                    completed, _ = wait(tuple(future_meta),
                                        return_when=FIRST_COMPLETED)
                    for future in completed:
                        seat, through = future_meta.pop(future)
                        active_by_seat.pop(seat.id, None)
                        self.busy.discard(seat.id)
                        name = self.sinaxa.seat_name(self.project, seat)
                        try:
                            answer, meta = future.result()
                        except Exception as exc:
                            answer, meta = None, {"error": str(exc)[:400]}
                        if answer is None:
                            self.post(meta.get("error", "engine failed"),
                                      author=seat.id, author_name=name,
                                      kind="error", meta=meta)
                            continue
                        if answer.strip().upper() in {"NO_REPLY", "[NO_REPLY]"}:
                            continue
                        reply = self.post(answer, author=seat.id,
                                          author_name=name, meta=meta)
                        mentioned = self.sinaxa.mentioned(
                            self.project, answer,
                            [one for one in participants if one.id != seat.id])
                        for target in mentioned:
                            enqueue(target, reply, True)

            if pending:
                self.post("Round paused after %d agent turns. Send a new "
                          "message to continue." % limit,
                          author="system", kind="boundary")

    def say(self, text, images=None):
        if not self.project.is_open:
            raise ModelError("open the project before sending a message")
        with self._lock:
            message = self.post(text, images=images)
            self.run_turn(message)
            return message

    def status(self):
        agents = []
        for seat_id, conversation in self.conversations.items():
            if conversation.agent:
                state = conversation.agent.status()
                state.update({"seat": seat_id})
                agents.append(state)
        return {"busy": sorted(self.busy), "agents": agents,
                "engines": self.engines.status()}
