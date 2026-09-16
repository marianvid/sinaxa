"""Conversation orchestration for one project session."""

import threading
import time

from .model import ModelError

MAX_HOPS = 3
TURN_TIMEOUT = 600
PREAMBLE = """You are {name}, occupying the {role} seat in project {project}.
This conversation is the session {session}. The human lead is {lead}.
Participants: {participants}.

Use @Name only when another participant should answer. Be conversational and
concise unless the lead asks for a detailed artifact.

Seat instructions:
{prompt}"""


class Conversation:
    def __init__(self, seat_id):
        self.seat_id = seat_id
        self.agent = None
        self.delivered = 0
        self.trouble = None


class Talk:
    def __init__(self, sinaxa, store, project, session, engines,
                 max_hops=MAX_HOPS):
        self.sinaxa = sinaxa
        self.store = store
        self.project = project
        self.session = session
        self.engines = engines
        self.max_hops = max_hops
        self.conversations = {}
        self.busy = set()
        self._lock = threading.RLock()

    def conversation(self, seat):
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

    def deliver(self, seat, message):
        agent = self.start(seat)
        if not agent:
            return None, {"error": self.conversation(seat).trouble}
        carried = bool(getattr(agent, "accepts_images", False))
        batch = self.context_for(seat, message["seq"])
        paths = []
        for item in batch:
            if carried:
                paths.extend(self.store.image_paths(self.project, self.session, item))
        answer, meta = agent.ask("\n".join(self.line(item, carried) for item in batch),
                                 timeout=TURN_TIMEOUT, images=paths)
        conversation = self.conversation(seat)
        conversation.delivered = message["seq"]
        native_id = agent.native_id() if hasattr(agent, "native_id") else None
        self.store.save_checkpoint(self.project, self.session, seat.id, {
            "native_id": native_id, "delivered": conversation.delivered,
            "engine": self.sinaxa.member(seat.occupant).engine})
        return answer, meta or {}

    def speakers_for(self, text, author_seat=None):
        seats = [seat for seat in self.participants()
                 if seat.id != author_seat and seat.occupant]
        return self.sinaxa.mentioned(self.project, text, seats) or seats

    def post(self, text, author="lead", author_name=None, kind=None,
             images=None, meta=None):
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
        hops = self.max_hops if hops is None else hops
        speakers = targets or self.speakers_for(message["text"], author_seat)
        follow = []
        for seat in speakers:
            self.busy.add(seat.id)
            try:
                answer, meta = self.deliver(seat, message)
                name = self.sinaxa.seat_name(self.project, seat)
                if answer is None:
                    self.post(meta.get("error", "engine failed"), author=seat.id,
                              author_name=name, kind="error", meta=meta)
                    continue
                reply = self.post(answer, author=seat.id, author_name=name, meta=meta)
                if hops > 0:
                    mentioned = self.sinaxa.mentioned(
                        self.project, answer,
                        [one for one in self.participants() if one.id != seat.id])
                    if mentioned:
                        follow.append((reply, seat.id, mentioned))
            finally:
                self.busy.discard(seat.id)
        for reply, source, mentioned in follow:
            self.run_turn(reply, source, hops - 1, mentioned)

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
