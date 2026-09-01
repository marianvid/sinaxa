"""Who hears what, who answers, and what a seat remembers.

One seat in one session is one conversation, however many rooms that seat
sits in. What it may read is decided by one rule and nothing else:

    a seat sees every message of every room it belongs to

The common room reaches everyone in it. A private room reaches its two
members. A room you made from a selection reaches that selection. None of
that needs a rule of its own -- it falls out of membership.

Because a seat reads several rooms, a message must say where it was said,
or the seat cannot tell what was public from what you told it alone. So
everything is delivered as

    [room - Name] the message

Messages arrive at a seat when it is asked something, not when they are
written: a seat that is not addressed accumulates what it has not seen and
is caught up on its next turn. That way, silence costs nothing.
"""

import threading
import time

MAX_HOPS = 3
TURN_TIMEOUT = 600

PREAMBLE = """You are {name}, {role} in the session "{session}" of the \
project "{project}", inside sinaxa -- a workspace where the members are AI \
agents and one human.

{lead} is the human and the lead, and is present in every room.
The seats in this session: {seats}.

Messages reach you prefixed with the room they were said in, as \
[room - Name]. A room is who can hear you: what is said in a shared room is \
read by everyone in it, and a room of two is between the two of you.

To address another member write @TheirName; the server delivers it and \
brings their answer back. Only do that when you need them -- every mention \
costs a model call.

Keep replies short. You are talking to colleagues, not writing \
documentation.

---

{prompt}"""


class Conversation:
    """The live side of one seat: its agent, and how much it has been told."""

    def __init__(self, seat_id):
        self.seat_id = seat_id
        self.agent = None
        self.delivered = 0          # highest seq this seat has been given
        self.trouble = None

    def status(self):
        base = {"seat": self.seat_id, "started": self.agent is not None,
                "trouble": self.trouble}
        if self.agent:
            base.update(self.agent.status())
        return base


class Talk:
    """Turn-taking for one session."""

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
        self._lock = threading.Lock()

    # ------------------------------------------------------------ context
    def conversation(self, seat):
        if seat.id not in self.conversations:
            self.conversations[seat.id] = Conversation(seat.id)
        return self.conversations[seat.id]

    def visible(self, seat):
        """Every message this seat is allowed to read, in order."""
        rooms = self.session.rooms_of(seat.id)
        return self.store.session_messages(self.project, self.session, rooms)

    def instructions_for(self, seat):
        lead = self.sinaxa.lead
        seats = ", ".join("%s (%s)" % (self.sinaxa.seat_name(s),
                                       self.sinaxa.seat_def(s.seat_def).role)
                          for s in self.session.seats)
        return PREAMBLE.format(
            name=self.sinaxa.seat_name(seat),
            role=self.sinaxa.seat_def(seat.seat_def).role,
            session=self.session.name, project=self.project.name,
            lead=lead.name if lead else "the human",
            seats=seats or "none yet",
            prompt=self.sinaxa.prompt_for(self.session, seat))

    def start(self, seat):
        """Bring a seat's agent up, or say why it cannot come up."""
        conversation = self.conversation(seat)
        trouble = self.sinaxa.seat_trouble(seat)
        if trouble:
            conversation.trouble = trouble
            return None
        if conversation.agent is None:
            member = self.sinaxa.member(seat.occupant)
            conversation.agent = self.engines.agent(
                member, self.sinaxa.seat_name(seat),
                self.instructions_for(seat))
            conversation.trouble = None
        return conversation.agent

    def clear(self, seat):
        """Forget the model's context. The transcript is untouched, and the
        seat is caught up from it on its next turn."""
        conversation = self.conversation(seat)
        if conversation.agent:
            conversation.agent.stop()
        conversation.agent = None
        conversation.delivered = 0
        return conversation

    # ------------------------------------------------------------ speaking
    def line(self, message):
        return "[%s - %s] %s" % (message.get("room_name", "?"),
                                 message.get("author_name", "?"),
                                 message.get("text", ""))

    def catch_up(self, seat, upto_seq):
        """What this seat has not been told yet, up to but excluding a
        message."""
        conversation = self.conversation(seat)
        unseen = [m for m in self.visible(seat)
                  if conversation.delivered < m.get("seq", 0) < upto_seq]
        return unseen

    def deliver(self, seat, message):
        """Ask one seat, giving it whatever it missed first."""
        agent = self.start(seat)
        if agent is None:
            return None, {"error": self.conversation(seat).trouble}
        conversation = self.conversation(seat)
        missed = self.catch_up(seat, message.get("seq", 0))
        body = "\n".join(self.line(m) for m in missed + [message])
        answer, meta = agent.ask(body, timeout=TURN_TIMEOUT)
        conversation.delivered = max(conversation.delivered,
                                     message.get("seq", 0))
        return answer, meta

    def speakers_for(self, room, text, author_seat_id):
        """Named with @ -> only them. Nobody named -> every seat in the room.

        The lead is not a seat and is never a speaker: it is you.
        """
        seats = [self.session.seat(sid) for sid in room.seats
                 if sid != author_seat_id]
        named = self.sinaxa.mentioned(text, seats)
        return named or seats

    # --------------------------------------------------------------- turn
    def post(self, room, author_seat_id, author_name, text, kind=None):
        """Write one message into a room and give it a place in the order."""
        self.session.seq += 1
        message = {"seq": self.session.seq, "room": room.id,
                   "room_name": room.name, "author": author_seat_id or "lead",
                   "author_name": author_name, "text": text,
                   "ts": time.time()}
        if kind:
            message["kind"] = kind
        self.store.append(self.project, self.session, room, message)
        self.store.save_session(self.project, self.session)
        return message

    def run_turn(self, room, message, author_seat_id, hops=None,
                 targets=None):
        """Ask whoever should answer, then follow their mentions.

        `targets` is set when one seat addressed another: that answer goes
        back to those seats only, never to the whole room. Without it, every
        reply is re-broadcast and the same question gets asked twice.
        """
        hops = self.max_hops if hops is None else hops
        speakers = (targets if targets is not None
                    else self.speakers_for(room, message["text"],
                                           author_seat_id))
        follow = []
        for seat in speakers:
            self.busy.add(seat.id)
            try:
                answer, meta = self.deliver(seat, message)
            finally:
                self.busy.discard(seat.id)
            if answer is None:
                self.post(room, seat.id, self.sinaxa.seat_name(seat),
                          "could not answer: %s" % meta.get("error", "?"),
                          kind="error")
                continue
            reply = self.post(room, seat.id, self.sinaxa.seat_name(seat),
                              answer)
            reply["meta"] = meta
            if hops > 0:
                others = [s for s in
                          (self.session.seat(sid) for sid in room.seats)
                          if s.id != seat.id]
                for target in self.sinaxa.mentioned(answer, others):
                    follow.append((reply, target))

        for reply, target in follow:
            self.run_turn(room, reply, reply["author"], hops - 1,
                          targets=[target])

    def say(self, room, text):
        """The lead writes into a room."""
        lead = self.sinaxa.lead
        message = self.post(room, None, lead.name if lead else "lead", text)
        self.run_turn(room, message, None)
        return message
