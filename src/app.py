"""What the interface can ask for: one method per thing you can do.

The HTTP layer in server.py turns requests into calls on this object and
nothing else, so every action can be tested without a socket.
"""

import atexit
import os

from . import engines as engines_mod
from .engines import Engines
from .model import ModelError, Sinaxa, blank_to_default
from .store import Store
from .talk import Talk


class App:
    def __init__(self, root, cwd=None, opencode_port=4096, binaries=None,
                 engines=None):
        self.store = Store(root)
        self.sinaxa = self.store.load()
        self.cwd = cwd or os.getcwd()
        self.engines = engines or Engines(self.cwd, binaries=binaries,
                                          opencode_port=opencode_port)
        self._talks = {}
        # A crash, a Ctrl-C, an exception on the way out: whatever happens,
        # nothing of ours outlives the interpreter.
        atexit.register(self.stop)

    # ------------------------------------------------------------ helpers
    def talk(self, project, session):
        key = (project.id, session.id)
        if key not in self._talks:
            self._talks[key] = Talk(self.sinaxa, self.store, project, session,
                                    self.engines)
        return self._talks[key]

    def locate(self, project_id, session_id=None, room_id=None):
        project = self.sinaxa.project(project_id)
        session = (project.session(session_id) if session_id
                   else (project.sessions[0] if project.sessions else None))
        room = session.room(room_id) if (session and room_id) else None
        return project, session, room

    # ----------------------------------------------------------- members
    def add_member(self, **kw):
        member = self.sinaxa.add_member(**kw)
        self.store.save_members(self.sinaxa)
        return member

    def update_member(self, member_id, **kw):
        member = self.sinaxa.update_member(member_id, **kw)
        self.store.save_members(self.sinaxa)
        self._forget_agents_of_member(member_id)
        return member

    def remove_member(self, member_id):
        member = self.sinaxa.remove_member(member_id)
        self.store.save_members(self.sinaxa)
        return member

    def _forget_agents_of_member(self, member_id):
        """A member changed engine or model: its live agents are stale."""
        for talk in self._talks.values():
            for seat in talk.session.seats:
                if seat.occupant == member_id:
                    talk.clear(seat)

    # ------------------------------------------------------------- roles
    def add_seat_def(self, **kw):
        definition = self.sinaxa.add_seat_def(**kw)
        self.store.save_seat_defs(self.sinaxa)
        return definition

    def update_seat_def(self, def_id, **kw):
        definition = self.sinaxa.update_seat_def(def_id, **kw)
        self.store.save_seat_defs(self.sinaxa)
        return definition

    def remove_seat_def(self, def_id):
        definition = self.sinaxa.remove_seat_def(def_id)
        self.store.save_seat_defs(self.sinaxa)
        return definition

    # ---------------------------------------------------------- projects
    def add_project(self, name, cwd=None):
        project = self.sinaxa.add_project(name, cwd=cwd)
        self.store.save_project(project)
        return project

    def remove_project(self, project_id, erase=False):
        """`erase` takes the transcripts off the disk too. Without it the
        project is only taken out of the picture and can be dug back out."""
        project = self.sinaxa.remove_project(project_id)
        for session in project.sessions:
            self._talks.pop((project.id, session.id), None)
        if erase:
            self.store.erase_project(project)
        else:
            self.store.forget_project(project)
        return project

    # ---------------------------------------------------------- sessions
    def add_session(self, project_id, name):
        project = self.sinaxa.project(project_id)
        session = project.add_session(name)
        self.store.save_project(project)
        return session

    def rename_session(self, project_id, session_id, name):
        project, session, _ = self.locate(project_id, session_id)
        session.name = name
        session.all_room.name = name
        self.store.save_session(project, session)
        return session

    def remove_session(self, project_id, session_id, erase=False):
        project = self.sinaxa.project(project_id)
        session = project.remove_session(session_id)
        talk = self._talks.pop((project.id, session.id), None)
        if talk:
            for seat in session.seats:
                talk.clear(seat)
        if erase:
            self.store.erase_session(project, session)
        self.store.save_project(project)
        return session

    # ------------------------------------------------------------- seats
    def add_seat(self, project_id, session_id, seat_def_id, occupant,
                 prompt=None):
        project, session, _ = self.locate(project_id, session_id)
        seat = self.sinaxa.add_seat(session, seat_def_id, occupant, prompt)
        self.store.save_session(project, session)
        return seat

    def update_seat(self, project_id, session_id, seat_id, occupant=None,
                    prompt=None):
        """Save, and restart the seat's process there and then.

        The prompt is only ever handed to a model when its process starts, so
        a changed prompt read by a process already running is no change at
        all. Rather than leave a button that quietly does nothing, the old
        process is stopped and a new one takes its place, which reads the
        rooms' transcripts back on its first turn. Returns whether that
        happened, so the interface can say so.

        An emptied prompt is not an empty prompt: it is the way back to the
        role's own.
        """
        project, session, _ = self.locate(project_id, session_id)
        seat = session.seat(seat_id)
        was = (seat.occupant, seat.prompt)

        if occupant is not None:
            self.sinaxa.member(occupant)
            seat.occupant = occupant
        if prompt is not None:
            seat.prompt = blank_to_default(prompt)

        restarted = False
        if (seat.occupant, seat.prompt) != was:
            restarted = self.talk(project, session).restart(seat)
        self.store.save_session(project, session)
        return seat, restarted

    def remove_seat(self, project_id, session_id, seat_id):
        project, session, _ = self.locate(project_id, session_id)
        seat = session.seat(seat_id)
        self.talk(project, session).clear(seat)
        session.remove_seat(seat_id)
        self.store.save_session(project, session)
        return seat

    def clear_seat_context(self, project_id, session_id, seat_id):
        project, session, _ = self.locate(project_id, session_id)
        seat = session.seat(seat_id)
        return self.talk(project, session).clear(seat)

    # ------------------------------------------------------------- rooms
    def add_room(self, project_id, session_id, name, seat_ids):
        project, session, _ = self.locate(project_id, session_id)
        room = session.add_room(name, seat_ids)
        self.store.save_session(project, session)
        return room

    def remove_room(self, project_id, session_id, room_id, erase=False):
        project, session, _ = self.locate(project_id, session_id)
        room = session.remove_room(room_id)
        if erase:
            self.store.erase_room(project, session, room)
        self.store.save_session(project, session)
        return room

    def add_seat_to_room(self, project_id, session_id, room_id, seat_id):
        project, session, _ = self.locate(project_id, session_id)
        room = session.add_seat_to_room(room_id, seat_id)
        self.store.save_session(project, session)
        return room

    def remove_seat_from_room(self, project_id, session_id, room_id, seat_id):
        project, session, _ = self.locate(project_id, session_id)
        room = session.remove_seat_from_room(room_id, seat_id)
        self.store.save_session(project, session)
        return room

    # ----------------------------------------------------------- talking
    def say(self, project_id, session_id, room_id, text):
        project, session, room = self.locate(project_id, session_id, room_id)
        return self.talk(project, session).say(room, text)

    def messages(self, project_id, session_id, room_id):
        project, session, room = self.locate(project_id, session_id, room_id)
        return self.store.messages(project, session, room)

    # ------------------------------------------------------------- state
    def state(self, project_id=None, session_id=None, room_id=None):
        """Everything the interface draws, in one answer."""
        sinaxa = self.sinaxa
        out = {
            "members": [m.as_dict() for m in sinaxa.members],
            "seat_defs": [d.as_dict() for d in sinaxa.seat_defs],
            "engines": engines_mod.describe(),
            "projects": [{"id": p.id, "name": p.name, "cwd": p.cwd,
                          "sessions": [{"id": s.id, "name": s.name}
                                       for s in p.sessions]}
                         for p in sinaxa.projects],
            "lead": sinaxa.lead.as_dict() if sinaxa.lead else None,
        }
        if not sinaxa.projects:
            return out

        project = (sinaxa.project(project_id) if project_id
                   else sinaxa.projects[0])
        session = (project.session(session_id) if session_id
                   else (project.sessions[0] if project.sessions else None))
        out["project"] = project.id
        if session is None:
            return out

        talk = self.talk(project, session)
        room = session.room(room_id) if room_id else session.all_room
        out["session"] = session.id
        out["room"] = room.id
        out["seats"] = [self._seat_state(talk, session, seat)
                        for seat in session.seats]
        out["rooms"] = [dict(r.as_dict(),
                             unread=0,
                             editable=not r.managed)
                        for r in session.rooms]
        out["messages"] = self.store.messages(project, session, room)
        out["busy"] = sorted(talk.busy)
        return out

    def _seat_state(self, talk, session, seat):
        definition = self.sinaxa.seat_def(seat.seat_def)
        member = self.sinaxa.find_member(seat.occupant)
        conversation = talk.conversations.get(seat.id)
        state = {
            "id": seat.id, "seat_def": seat.seat_def, "role": definition.role,
            "occupant": seat.occupant,
            "name": self.sinaxa.seat_name(seat),
            "member": member.as_dict() if member else None,
            "prompt": seat.prompt,
            "prompt_default": definition.prompt,
            "prompt_effective": self.sinaxa.prompt_for(session, seat),
            "overridden": seat.prompt is not None,
            "trouble": self.sinaxa.seat_trouble(seat),
            "rooms": [r.id for r in session.rooms_of(seat.id)],
            "started": bool(conversation and conversation.agent),
        }
        if conversation and conversation.agent:
            state["live"] = conversation.agent.status()
        return state

    def models_for(self, engine):
        return self.engines.models_for(engine)

    def stop(self):
        """Take everything down: agents first, then the backends they sat in.

        Called on the way out of the server, and again by atexit, so it must
        be safe to call twice.
        """
        for talk in self._talks.values():
            for seat in list(talk.session.seats):
                try:
                    talk.clear(seat)
                except Exception:
                    pass
        self.engines.stop()


__all__ = ["App", "ModelError", "Sinaxa"]
