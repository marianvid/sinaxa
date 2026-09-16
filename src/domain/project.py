import time

from .constants import CLOSED, CUSTOM, DIRECT, OPEN, TEAM
from .errors import ModelError
from .identity import new_id
from .seat import Seat
from .session import Session


class Project:
    """A restorable team, its working folder and independent sessions."""

    def __init__(self, name, id=None, cwd=None, state=OPEN, seats=None,
                 sessions=None, type_id=None):
        if not (name or "").strip():
            raise ModelError("a project needs a name")
        if state not in (OPEN, CLOSED):
            raise ModelError("a project must be open or closed")
        self.id = id or new_id("prj")
        self.name = name.strip()
        self.cwd = cwd
        self.state = state
        self.type_id = type_id or None
        self.seats = list(seats or [])
        self.sessions = list(sessions or [])
        if not any(session.kind == TEAM for session in self.sessions):
            self.sessions.insert(0, Session("Team", [], TEAM))

    @property
    def is_open(self):
        return self.state == OPEN

    @property
    def team_session(self):
        return next(session for session in self.sessions if session.kind == TEAM)

    def seat(self, seat_id):
        for seat in self.seats:
            if seat.id == seat_id:
                return seat
        raise ModelError("no such seat")

    def session(self, session_id):
        for session in self.sessions:
            if session.id == session_id:
                return session
        raise ModelError("no such session")

    def direct_session(self, seat_id):
        return next((session for session in self.sessions
                     if session.kind == DIRECT
                     and session.participants == [seat_id]), None)

    def add_seat(self, role, prompt, occupant=None, template_id=None):
        if not template_id:
            raise ModelError("a project seat must use a global seat definition")
        if any(seat.role.casefold() == role.strip().casefold()
               for seat in self.seats):
            raise ModelError("that role already exists in this project")
        seat = Seat(role, prompt, occupant, template_id=template_id)
        self.seats.append(seat)
        self.team_session.participants.append(seat.id)
        self.sessions.append(Session(role, [seat.id], DIRECT,
                                     created_at=time.time()))
        return seat

    def remove_seat(self, seat_id):
        seat = self.seat(seat_id)
        direct = self.direct_session(seat_id)
        self.seats.remove(seat)
        if direct:
            self.sessions.remove(direct)
        for session in self.sessions:
            if seat_id in session.participants:
                session.participants.remove(seat_id)
        return seat, direct

    def add_session(self, name, participants):
        wanted = list(dict.fromkeys(participants or []))
        if not wanted:
            raise ModelError("a session needs at least one seat")
        for seat_id in wanted:
            self.seat(seat_id)
        session = Session(name, wanted, CUSTOM, created_at=time.time())
        self.sessions.append(session)
        return session

    def remove_session(self, session_id):
        session = self.session(session_id)
        if session.managed:
            raise ModelError("direct and team sessions cannot be removed")
        self.sessions.remove(session)
        return session

    def as_dict(self):
        return {"id": self.id, "name": self.name, "cwd": self.cwd,
                "state": self.state, "type_id": self.type_id,
                "seats": [seat.as_dict() for seat in self.seats],
                "sessions": [session.as_dict() for session in self.sessions]}

    @classmethod
    def from_dict(cls, raw):
        raw = dict(raw)
        raw["seats"] = [Seat.from_dict(one) for one in raw.get("seats", [])]
        raw["sessions"] = [Session.from_dict(one)
                           for one in raw.get("sessions", [])]
        return cls(**raw)
