"""The structures, and only the structures.

    Sinaxa
     |- members[]     Member    an engine plus a model: how an occupant starts
     |- seat_defs[]   SeatDef   a role plus its default prompt
     +- projects[]    Project
          +- sessions[]  Session   seats live here; the prompt is overridden here
               |- seats[]  Seat    a role, taken by a member, inside one session
               +- rooms[]  Room    a grouping of seats, nothing more

Nothing in this file knows about Claude, Codex, opencode or any person. It
holds lists. Talking to a provider is src/engines/, disk is src/store.py.

Two rules earn their place here because everything else follows from them:

  * A seat is the unit of conversation. One seat in one session is one
    context, however many rooms it sits in.
  * A seat sees every message of every room it belongs to. That is the whole
    of the context model: the common room reaches everyone in it, a private
    room reaches only its own members, and no rule beyond membership is
    needed to say so.
"""

import re
import uuid

HUMAN, AGENT = "human", "agent"
ALL, PRIVATE, CUSTOM = "all", "private", "custom"

# A member is recognised by its colour everywhere it appears -- the avatar in
# the thread, the swatch in the sidebar, the pill in the header. Handed out in
# order so that two members are never the same colour by accident.
PALETTE = ["#2f6fd0", "#c96442", "#3fbf7f", "#7c6cf0", "#e0a53f", "#38a9a2",
           "#d05f9c", "#8a9a3b"]


def new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


class ModelError(Exception):
    """A rule was broken. The message is meant to be shown to the user."""


def blank_to_default(prompt):
    """An override that has been emptied is not an empty prompt -- it is the
    way back to the role's own. A seat is never without instructions."""
    if prompt is None or not prompt.strip():
        return None
    return prompt


# --------------------------------------------------------------- members
class Member:
    """Who can take a seat: a human, or an engine started a particular way."""

    def __init__(self, name, kind=AGENT, engine=None, model=None, effort=None,
                 binary=None, id=None, colour=None):
        if kind == AGENT and not engine:
            raise ModelError("an agent needs an engine")
        self.id = id or new_id("mem")
        self.name = name
        self.kind = kind
        self.engine = engine
        self.model = model
        self.effort = effort
        self.binary = binary
        self.colour = colour

    @property
    def is_human(self):
        return self.kind == HUMAN

    def as_dict(self):
        return {"id": self.id, "name": self.name, "kind": self.kind,
                "engine": self.engine, "model": self.model,
                "effort": self.effort, "binary": self.binary,
                "colour": self.colour}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class SeatDef:
    """A role, defined once for the whole of sinaxa.

    `prompt` is the default an occupant is given. A session may override it;
    a room never does -- a room only decides who is in the conversation.
    """

    def __init__(self, role, prompt="", default_member=None, id=None):
        if not role.strip():
            raise ModelError("a role needs a name")
        if not (prompt or "").strip():
            raise ModelError("a role needs a prompt -- it is what its "
                             "occupant is told it does")
        self.id = id or new_id("def")
        self.role = role
        self.prompt = prompt
        self.default_member = default_member

    def as_dict(self):
        return {"id": self.id, "role": self.role, "prompt": self.prompt,
                "default_member": self.default_member}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


# ------------------------------------------------------------ the session
class Seat:
    """A role taken by a member, inside one session.

    There is no such thing as an empty seat: a seat exists because somebody
    occupies it. An occupant can go *missing* -- the member deleted, its
    binary moved, its model gone from the engine's config -- and then the
    seat says so and waits to be given a new one.

    A prompt is never empty. `prompt` is either an override, or None meaning
    the role's own. Blanking an override is how you go back to the role's --
    there is nothing else emptiness could sensibly mean, and an occupant
    with no instructions at all is not a state we allow.
    """

    def __init__(self, seat_def, occupant, prompt=None, id=None):
        self.id = id or new_id("seat")
        self.seat_def = seat_def
        self.occupant = occupant
        self.prompt = blank_to_default(prompt)

    def as_dict(self):
        return {"id": self.id, "seat_def": self.seat_def,
                "occupant": self.occupant, "prompt": self.prompt}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class Room:
    """A grouping of seats. The lead is in every room and is not a seat.

        all      every seat of the session; maintained by sinaxa
        private  one seat; created and removed with it
        custom   yours: any selection of seats

    Only custom rooms take seats in and out. The other two follow the
    session, so that "who is in the team room" is never a second answer to
    "who is in the team".
    """

    def __init__(self, name, seats=None, kind=CUSTOM, id=None):
        self.id = id or new_id("room")
        self.name = name
        self.seats = list(seats or [])
        self.kind = kind

    @property
    def managed(self):
        return self.kind in (ALL, PRIVATE)

    def as_dict(self):
        return {"id": self.id, "name": self.name, "seats": self.seats,
                "kind": self.kind}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class Session:
    """Seats live here, and so does the prompt override.

    Creating a session gives you the room with everyone in it. Every seat you
    add brings its own private room along.
    """

    def __init__(self, name, id=None, seats=None, rooms=None, seq=0):
        self.id = id or new_id("ses")
        self.name = name
        self.seats = list(seats or [])
        self.rooms = list(rooms or [])
        self.seq = seq                  # next message number, session-wide
        if not self.rooms:
            self.rooms.append(Room(name, [], ALL))

    # ----------------------------------------------------------- lookups
    @property
    def all_room(self):
        return next(r for r in self.rooms if r.kind == ALL)

    def room(self, room_id):
        for room in self.rooms:
            if room.id == room_id:
                return room
        raise ModelError("no such room")

    def seat(self, seat_id):
        for seat in self.seats:
            if seat.id == seat_id:
                return seat
        raise ModelError("no such seat")

    def private_room_of(self, seat_id):
        for room in self.rooms:
            if room.kind == PRIVATE and room.seats == [seat_id]:
                return room
        return None

    def rooms_of(self, seat_id):
        """Every room a seat is in -- which is exactly what it may read."""
        return [r for r in self.rooms if seat_id in r.seats]

    # ------------------------------------------------------------ seats
    def add_seat(self, seat_def_id, occupant, prompt=None, role_name="seat"):
        seat = Seat(seat_def_id, occupant, prompt)
        self.seats.append(seat)
        self.all_room.seats.append(seat.id)
        self.rooms.append(Room(role_name, [seat.id], PRIVATE))
        return seat

    def remove_seat(self, seat_id):
        seat = self.seat(seat_id)
        self.seats.remove(seat)
        for room in list(self.rooms):
            if seat_id in room.seats:
                room.seats.remove(seat_id)
                if not room.seats and room.kind != ALL:
                    self.rooms.remove(room)
        return seat

    # ------------------------------------------------------------ rooms
    def add_room(self, name, seat_ids):
        if not seat_ids:
            raise ModelError("a room needs at least one seat besides the lead")
        for seat_id in seat_ids:
            self.seat(seat_id)
        room = Room(name, list(seat_ids), CUSTOM)
        self.rooms.append(room)
        return room

    def remove_room(self, room_id):
        room = self.room(room_id)
        if room.managed:
            raise ModelError("%s rooms follow the session and cannot be "
                             "removed on their own" % room.kind)
        self.rooms.remove(room)
        return room

    def add_seat_to_room(self, room_id, seat_id):
        room = self.room(room_id)
        if room.managed:
            raise ModelError("%s rooms follow the session; make a room of "
                             "your own to group seats differently" % room.kind)
        self.seat(seat_id)
        if seat_id not in room.seats:
            room.seats.append(seat_id)
        return room

    def remove_seat_from_room(self, room_id, seat_id):
        room = self.room(room_id)
        if room.managed:
            raise ModelError("%s rooms follow the session" % room.kind)
        if len(room.seats) <= 1:
            raise ModelError("that is the room's last seat -- remove the room "
                             "instead")
        room.seats.remove(seat_id)
        return room

    # ------------------------------------------------------------- disk
    def as_dict(self):
        return {"id": self.id, "name": self.name, "seq": self.seq,
                "seats": [s.as_dict() for s in self.seats],
                "rooms": [r.as_dict() for r in self.rooms]}

    @classmethod
    def from_dict(cls, raw):
        return cls(name=raw["name"], id=raw["id"], seq=raw.get("seq", 0),
                   seats=[Seat.from_dict(s) for s in raw.get("seats", [])],
                   rooms=[Room.from_dict(r) for r in raw.get("rooms", [])])


class Project:
    def __init__(self, name, id=None, sessions=None, cwd=None):
        self.id = id or new_id("prj")
        self.name = name
        self.cwd = cwd
        self.sessions = list(sessions or [])

    def session(self, session_id):
        for session in self.sessions:
            if session.id == session_id:
                return session
        raise ModelError("no such session")

    def add_session(self, name):
        session = Session(name)
        self.sessions.append(session)
        return session

    def remove_session(self, session_id):
        session = self.session(session_id)
        if len(self.sessions) == 1:
            raise ModelError("a project keeps at least one session")
        self.sessions.remove(session)
        return session

    def as_dict(self):
        return {"id": self.id, "name": self.name, "cwd": self.cwd,
                "sessions": [s.id for s in self.sessions]}


# ---------------------------------------------------------------- sinaxa
class Sinaxa:
    """The root. Members and roles are defined once, here, and used
    everywhere; projects are the work."""

    def __init__(self, members=None, seat_defs=None, projects=None):
        self.members = list(members or [])
        self.seat_defs = list(seat_defs or [])
        self.projects = list(projects or [])

    # ---------------------------------------------------------- lookups
    def member(self, member_id):
        for member in self.members:
            if member.id == member_id:
                return member
        raise ModelError("no such member")

    def find_member(self, member_id):
        """Like member(), but None instead of raising -- a missing occupant
        is a state to show, not a crash."""
        try:
            return self.member(member_id)
        except ModelError:
            return None

    def seat_def(self, def_id):
        for definition in self.seat_defs:
            if definition.id == def_id:
                return definition
        raise ModelError("no such seat definition")

    def project(self, project_id):
        for project in self.projects:
            if project.id == project_id:
                return project
        raise ModelError("no such project")

    @property
    def lead(self):
        for member in self.members:
            if member.is_human:
                return member
        return None

    # ---------------------------------------------------------- members
    def add_member(self, **kw):
        member = Member(**kw)
        if member.is_human and self.lead:
            raise ModelError("there is already a human lead: %s"
                             % self.lead.name)
        if any(m.name.lower() == member.name.lower() for m in self.members):
            raise ModelError("a member called %s already exists" % member.name)
        if not member.colour:
            taken = {m.colour for m in self.members}
            free = [c for c in PALETTE if c not in taken]
            member.colour = (free or PALETTE)[0]
        self.members.append(member)
        return member

    def update_member(self, member_id, **kw):
        member = self.member(member_id)
        for field, value in kw.items():
            if field in ("id", "kind"):
                continue
            setattr(member, field, value)
        return member

    def uses_member(self, member_id):
        """Every (project, session, seat) that member occupies."""
        found = []
        for project in self.projects:
            for session in project.sessions:
                for seat in session.seats:
                    if seat.occupant == member_id:
                        found.append((project, session, seat))
        return found

    def remove_member(self, member_id):
        member = self.member(member_id)
        taken = self.uses_member(member_id)
        if taken:
            where = ", ".join("%s / %s" % (p.name, s.name) for p, s, _ in taken)
            raise ModelError("%s still occupies a seat in %s -- give those "
                             "seats another occupant first"
                             % (member.name, where))
        self.members.remove(member)
        return member

    # ------------------------------------------------------------ roles
    def add_seat_def(self, **kw):
        definition = SeatDef(**kw)
        if any(d.role.lower() == definition.role.lower()
               for d in self.seat_defs):
            raise ModelError("a role called %s already exists"
                             % definition.role)
        self.seat_defs.append(definition)
        return definition

    def update_seat_def(self, def_id, **kw):
        definition = self.seat_def(def_id)
        if "prompt" in kw and not (kw["prompt"] or "").strip():
            raise ModelError("a role needs a prompt -- it is what its "
                             "occupant is told it does")
        for field, value in kw.items():
            if field != "id":
                setattr(definition, field, value)
        return definition

    def uses_seat_def(self, def_id):
        found = []
        for project in self.projects:
            for session in project.sessions:
                for seat in session.seats:
                    if seat.seat_def == def_id:
                        found.append((project, session, seat))
        return found

    def remove_seat_def(self, def_id):
        definition = self.seat_def(def_id)
        taken = self.uses_seat_def(def_id)
        if taken:
            where = ", ".join("%s / %s" % (p.name, s.name) for p, s, _ in taken)
            raise ModelError("the role %s is in use in %s -- remove those "
                             "seats first" % (definition.role, where))
        self.seat_defs.remove(definition)
        return definition

    # --------------------------------------------------------- projects
    def add_project(self, name, cwd=None):
        """A new project starts as your team already is: one session, every
        role that has a default occupant, and a room each."""
        if any(p.name.lower() == name.lower() for p in self.projects):
            raise ModelError("a project called %s already exists" % name)
        project = Project(name, cwd=cwd)
        session = project.add_session("main")
        for definition in self.seat_defs:
            if definition.default_member and \
                    self.find_member(definition.default_member):
                session.add_seat(definition.id, definition.default_member,
                                 role_name=definition.role)
        self.projects.append(project)
        return project

    def remove_project(self, project_id):
        project = self.project(project_id)
        self.projects.remove(project)
        return project

    # ------------------------------------------------------------ seats
    def add_seat(self, session, seat_def_id, occupant, prompt=None):
        definition = self.seat_def(seat_def_id)
        self.member(occupant)
        if any(s.seat_def == seat_def_id for s in session.seats):
            raise ModelError("%s is already a seat in this session"
                             % definition.role)
        return session.add_seat(seat_def_id, occupant, prompt,
                                role_name=definition.role)

    def prompt_for(self, session, seat):
        """The session's override, or the role's default."""
        if seat.prompt is not None:
            return seat.prompt
        return self.seat_def(seat.seat_def).prompt

    def seat_name(self, seat):
        """What a seat is called in a transcript: its occupant's name."""
        member = self.find_member(seat.occupant)
        if member:
            return member.name
        return self.seat_def(seat.seat_def).role

    def seat_trouble(self, seat):
        """Why this seat cannot run, or None."""
        if self.find_member(seat.occupant) is None:
            return "its occupant no longer exists -- give it another"
        return None

    def mentioned(self, text, seats):
        """@Name, on a word boundary, case-insensitively."""
        out = []
        for seat in seats:
            name = self.seat_name(seat)
            if re.search(r"@%s\b" % re.escape(name), text, re.IGNORECASE):
                out.append(seat)
        return out
