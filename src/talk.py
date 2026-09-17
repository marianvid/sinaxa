"""Conversation orchestration for one project session."""

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .conversation import Conversation
from .domain import ModelError

PREAMBLE = """You are {name}, a persistent member of project {project}.
The human lead is {lead}. Your project roles and instructions are:
{roles}

Project members: {participants}.

Communication between participants is mediated by this transcript. To ask
another participant to answer, address them as @Name. Do not use provider-native
agent messaging or agent-discovery tools for Sinaxa participants. Messages are
labelled with their Sinaxa channel. Main-channel messages are visible to every
project member; direct-channel messages are private to you and the human lead;
group-channel messages are visible only to that group's participants. Private
information may inform your reasoning, but do not reveal it in another channel
unless the human lead explicitly asks you to do so. A routing note at the end
of each delivery says whether a visible reply is required. If you mention
another participant, you explicitly request another turn from them. Be
conversational and concise unless the lead asks for a detailed artifact."""


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
        member = self.sinaxa.member(seat.occupant)
        member_seats = [one for one in self.project.seats
                        if one.occupant == member.id]
        return PREAMBLE.format(
            name=member.name, project=self.project.name,
            lead=lead.name if lead else "the human lead",
            participants=", ".join(
                "%s (%s)" % (self.sinaxa.seat_name(self.project, one), one.role)
                for one in self.project.seats),
            roles="\n".join("- %s: %s" % (one.role, one.prompt)
                            for one in member_seats))

    def start(self, seat):
        conversation = self.conversation(seat)
        trouble = self.sinaxa.seat_trouble(self.project, seat)
        if trouble:
            conversation.trouble = trouble
            return None
        member = self.sinaxa.member(seat.occupant)
        if (conversation.agent is not None
                and hasattr(self.engines, "is_current")
                and not self.engines.is_current(member.id,
                                                conversation.agent)):
            conversation.agent = None
        if conversation.agent is None:
            checkpoint = self.store.agent_contexts(self.project).get(
                member.id, {})
            already_live = (self.engines.has_agent(member.id)
                            if hasattr(self.engines, "has_agent") else False)
            conversation.agent = self.engines.agent(
                member, member.name,
                self.instructions_for(seat), native_id=checkpoint.get("native_id"))
            if (not already_live and checkpoint.get("native_id") and not getattr(
                    conversation.agent, "resumed", False)):
                self.store.save_agent_context(self.project, member.id, None)
            conversation.trouble = None
        return conversation.agent

    def stop(self):
        """Detach this session view; the project runtime owns live agents."""
        for conversation in self.conversations.values():
            conversation.agent = None

    def clear_context(self):
        """Start a new context epoch while keeping the visible transcript."""
        with self._lock:
            members = set()
            for seat in self.participants():
                if self.sinaxa.seat_runs_engine(seat):
                    members.add(seat.occupant)
            for member_id in members:
                if hasattr(self.engines, "reset_agent"):
                    self.engines.reset_agent(member_id)
                self.store.save_agent_context(self.project, member_id, None)
            self.conversations.clear()
            self.session.context_start_seq = self.session.seq + 1
            self.store.save_project(self.project)
            return self.post(
                "Context cleared — earlier messages remain in the transcript "
                "but are no longer sent to agents.",
                author="system", kind="boundary")

    def line(self, message, carried=True):
        count = len(message.get("images", []))
        note = ""
        if count:
            note = " [%d image%s %s]" % (
                count, "" if count == 1 else "s",
                "attached" if carried else "not supported by this engine")
        session_name = message.get("_session_name", self.session.name)
        visibility = message.get("_visibility", "session")
        return "[%s · %s] %s: %s%s" % (session_name, visibility,
                                   message.get("author_name", "?"),
                                   message.get("text", ""), note)

    def context_for(self, seat, through):
        member = self.sinaxa.member(seat.occupant)
        member_seats = {one.id for one in self.project.seats
                        if one.occupant == member.id}
        checkpoint = self.store.agent_contexts(self.project).get(member.id, {})
        delivered = checkpoint.get("delivered") or {}
        batch = []
        for session in self.project.sessions:
            if not member_seats.intersection(session.participants):
                continue
            cursor = int(delivered.get(session.id, 0))
            for stored in self.store.messages(self.project, session):
                seq = stored.get("seq", 0)
                if seq <= cursor or seq < session.context_start_seq:
                    continue
                if stored.get("kind") in ("boundary", "compaction"):
                    continue
                if session.id == self.session.id and seq > through["seq"]:
                    continue
                if stored.get("ts", 0) > through.get("ts", float("inf")):
                    continue
                message = dict(stored)
                message["_session_id"] = session.id
                message["_session_name"] = (
                    "Main" if session.kind == "team" else session.name)
                message["_visibility"] = (
                    "private" if session.kind == "direct" else
                    "team" if session.kind == "team" else "group")
                batch.append(message)
        return sorted(batch, key=lambda item: (
            item.get("ts", 0), item["_session_id"], item.get("seq", 0)))

    def deliver(self, seat, message, required=False):
        agent = self.start(seat)
        if not agent:
            return None, {"error": self.conversation(seat).trouble}
        member = self.sinaxa.member(seat.occupant)
        lock = (self.engines.agent_lock(member.id)
                if hasattr(self.engines, "agent_lock") else self._lock)
        with lock:
            batch = self.context_for(seat, message)
            carried = bool(getattr(agent, "accepts_images", False))
            paths = []
            for item in batch:
                if carried:
                    source = self.project.session(item["_session_id"])
                    paths.extend(self.store.image_paths(
                        self.project, source, item))
            routing = ("[Sinaxa routing] Reply in channel %s. This turn "
                       "requires your visible answer." % self.session.name
                       if required else
                       "[Sinaxa routing] Update your awareness, but do not "
                       "produce a visible reply; return exactly [NO_REPLY].")
            prompt = "\n".join(self.line(item, carried) for item in batch)
            prompt = "%s\n\n%s" % (prompt, routing)
            answer, meta = agent.ask(
                prompt, timeout=self.session.turn_timeout, images=paths)
            checkpoint = self.store.agent_contexts(self.project).get(
                member.id, {})
            delivered = dict(checkpoint.get("delivered") or {})
            for item in batch:
                source_id = item["_session_id"]
                delivered[source_id] = max(
                    int(delivered.get(source_id, 0)), item.get("seq", 0))
            self.store.save_agent_context(self.project, member.id, {
                "native_id": (agent.native_id()
                              if hasattr(agent, "native_id") else None),
                "delivered": delivered, "engine": member.engine})
            self.conversation(seat).delivered = int(
                delivered.get(self.session.id, 0))
            return answer, meta or {}

    def acknowledge(self, seat, message):
        """Record an agent's own reply as already present in native context."""
        member = self.sinaxa.member(seat.occupant)
        checkpoint = self.store.agent_contexts(self.project).get(member.id, {})
        delivered = dict(checkpoint.get("delivered") or {})
        delivered[self.session.id] = max(
            int(delivered.get(self.session.id, 0)), message.get("seq", 0))
        agent = self.conversation(seat).agent
        self.store.save_agent_context(self.project, member.id, {
            "native_id": (agent.native_id()
                          if agent and hasattr(agent, "native_id") else
                          checkpoint.get("native_id")),
            "delivered": delivered, "engine": member.engine})
        self.conversation(seat).delivered = delivered[self.session.id]

    def speakers_for(self, text, author_seat=None):
        seats = [seat for seat in self.participants()
                 if seat.id != author_seat
                 and self.sinaxa.seat_runs_engine(seat)]
        mentioned = self.sinaxa.mentioned(self.project, text, seats)
        if author_seat is None:
            return mentioned or seats
        return mentioned

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
                member = self.sinaxa.member(seat.occupant)
                delivered = (self.store.agent_contexts(self.project)
                             .get(member.id, {}).get("delivered", {}))
                if int(delivered.get(self.session.id, 0)) >= through["seq"]:
                    return
                queued = pending.get(seat.id)
                if not queued or through["seq"] > queued[1]["seq"]:
                    pending[seat.id] = (seat, through, required)
                elif required:
                    pending[seat.id] = (queued[0], queued[1], True)

            for seat in initial:
                enqueue(seat, message, author_seat is None or
                        seat.id in explicitly_mentioned)

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
                        if meta.get("compacted"):
                            details = meta.get("compaction") or {}
                            trigger = details.get("trigger")
                            suffix = " (%s)" % trigger if trigger else ""
                            self.post("%s compacted native context%s" %
                                      (name, suffix), author="system",
                                      kind="compaction",
                                      meta={"seat": seat.id,
                                            "engine": self.sinaxa.member(
                                                seat.occupant).engine,
                                            "compaction": details})
                        reply = self.post(answer, author=seat.id,
                                          author_name=name, meta=meta)
                        self.acknowledge(seat, reply)
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
