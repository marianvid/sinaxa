"""Application facade and composition root used by HTTP and tests."""

import atexit
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from .domain import CLOSED, CUSTOM, OPEN, EngineConfig, ModelError
from .runtime import RuntimeManager, describe
from .store import Store
from .talk import Talk


class App:
    def __init__(self, root, cwd=None, engines=None, runtime_factory=None):
        self.store = Store(root)
        self.sinaxa = self.store.load()
        self.cwd = cwd or os.getcwd()
        self._fixed_engines = engines
        if engines and not runtime_factory:
            runtime_factory = lambda project: engines
        self.runtimes = RuntimeManager(self.sinaxa, factory=runtime_factory)
        self._talks = {}
        self._jobs = {}
        self._executor = ThreadPoolExecutor(max_workers=16,
                                            thread_name_prefix="sinaxa-turn")
        self._lock = threading.RLock()
        self._stopped = False
        atexit.register(self.stop)

    def locate(self, project_id, session_id=None):
        project = self.sinaxa.project(project_id)
        session = project.session(session_id) if session_id else project.team_session
        return project, session

    def talk(self, project, session):
        key = (project.id, session.id)
        if key not in self._talks:
            runtime = self.runtimes.for_project(project)
            self._talks[key] = Talk(self.sinaxa, self.store, project, session,
                                    runtime)
        return self._talks[key]

    # engines -------------------------------------------------------------
    def update_engine(self, engine_id, **fields):
        with self._lock:
            engine = self.sinaxa.engine(engine_id)
            allowed = {"name", "enabled", "executable", "mode", "streaming",
                       "max_concurrency", "mcp_servers", "options"}
            candidate = engine.as_dict()
            candidate.update({key: value for key, value in fields.items()
                              if key in allowed})
            if candidate.get("mode") != "persistent":
                raise ModelError(
                    "non-persistent engine mode is not yet implemented")
            replacement = EngineConfig.from_dict(candidate)
            self.sinaxa.engines[self.sinaxa.engines.index(engine)] = replacement
            self.store.save_engines(self.sinaxa)
            for project in self.sinaxa.projects:
                self.runtimes.close(project.id)
            self._talks.clear()
            return replacement

    def models_for(self, engine_id, project_id=None):
        engine = self.sinaxa.engine(engine_id)
        if project_id:
            project = self.sinaxa.project(project_id)
        else:
            project = next((p for p in self.sinaxa.projects if p.is_open), None)
        if not project:
            return []
        return self.runtimes.for_project(project).models_for(engine.id)

    # members -------------------------------------------------------------
    def add_member(self, **fields):
        with self._lock:
            member = self.sinaxa.add_member(**fields)
            self.store.save_members(self.sinaxa)
            return member

    def update_member(self, member_id, **fields):
        with self._lock:
            member = self.sinaxa.update_member(member_id, **fields)
            self.store.save_members(self.sinaxa)
            self._drop_member_conversations(member_id)
            return member

    def remove_member(self, member_id):
        with self._lock:
            member = self.sinaxa.remove_member(member_id)
            self.store.save_members(self.sinaxa)
            return member

    def _drop_member_conversations(self, member_id):
        for project in self.sinaxa.projects:
            if any(seat.occupant == member_id for seat in project.seats):
                self._reset_project_agent(project, member_id)

    def _reset_project_agent(self, project, member_id):
        if not member_id:
            return
        self.runtimes.reset_agent(project.id, member_id)
        self.store.save_agent_context(project, member_id, None)
        seat_ids = {seat.id for seat in project.seats
                    if seat.occupant == member_id}
        for (project_id, _), talk in self._talks.items():
            if project_id != project.id:
                continue
            for seat_id in seat_ids:
                talk.conversations.pop(seat_id, None)

    # projects ------------------------------------------------------------
    def add_project(self, name, cwd=None, type_id=None):
        with self._lock:
            project = self.sinaxa.add_project(name, cwd or self.cwd, type_id)
            self.store.save_project(project)
            return project

    def update_project(self, project_id, **fields):
        if "state" in fields:
            self.set_project_open(project_id, fields["state"] == OPEN)
        with self._lock:
            project = self.sinaxa.project(project_id)
            if "name" in fields:
                name = (fields["name"] or "").strip()
                if not name:
                    raise ModelError("a project needs a name")
                project.name = name
            if "cwd" in fields:
                project.cwd = fields["cwd"] or self.cwd
            self.store.save_project(project)
            return project

    def set_project_open(self, project_id, opened):
        project = self.sinaxa.project(project_id)
        if not opened:
            self._wait_project(project.id)
            for key, talk in list(self._talks.items()):
                if key[0] == project.id:
                    talk.stop()
                    self._talks.pop(key, None)
            self.runtimes.close(project.id)
        project.state = OPEN if opened else CLOSED
        self.store.save_project(project)
        return project

    def remove_project(self, project_id, erase=False):
        project = self.sinaxa.project(project_id)
        self.set_project_open(project_id, False)
        self.sinaxa.remove_project(project_id)
        if erase:
            self.store.erase_project(project)
        else:
            self.store.archive_project(project)
        return project

    # seats ---------------------------------------------------------------
    # reusable seat templates --------------------------------------------
    def add_seat_template(self, **fields):
        with self._lock:
            template = self.sinaxa.add_seat_template(**fields)
            self.store.save_seat_templates(self.sinaxa)
            return template

    def update_seat_template(self, template_id, **fields):
        with self._lock:
            template = self.sinaxa.update_seat_template(template_id, **fields)
            self.store.save_seat_templates(self.sinaxa)
            return template

    def remove_seat_template(self, template_id):
        with self._lock:
            template = self.sinaxa.remove_seat_template(template_id)
            self.store.save_seat_templates(self.sinaxa)
            return template

    # project types ------------------------------------------------------
    def add_project_type(self, **fields):
        with self._lock:
            project_type = self.sinaxa.add_project_type(**fields)
            self.store.save_project_types(self.sinaxa)
            return project_type

    def update_project_type(self, type_id, **fields):
        with self._lock:
            project_type = self.sinaxa.update_project_type(type_id, **fields)
            self.store.save_project_types(self.sinaxa)
            return project_type

    def remove_project_type(self, type_id):
        with self._lock:
            project_type = self.sinaxa.remove_project_type(type_id)
            self.store.save_project_types(self.sinaxa)
            return project_type

    # project seats ------------------------------------------------------
    def add_seat(self, project_id, template_id, occupant=None, prompt=None):
        with self._lock:
            project = self.sinaxa.project(project_id)
            seat = self.sinaxa.add_project_seat(
                project_id, template_id, occupant, prompt)
            self.store.save_project(project)
            return seat

    def update_seat(self, project_id, seat_id, **fields):
        with self._lock:
            project = self.sinaxa.project(project_id)
            seat = project.seat(seat_id)
            previous_occupant = seat.occupant
            if "occupant" in fields:
                occupant = fields["occupant"] or None
                if occupant:
                    self.sinaxa.member(occupant)
                seat.occupant = occupant
            if "role" in fields and fields["role"].strip():
                seat.role = fields["role"].strip()
                direct = project.direct_session(seat.id)
                if direct:
                    direct.name = seat.role
            if "prompt" in fields and fields["prompt"].strip():
                seat.prompt = fields["prompt"]
            self._drop_seat_conversations(
                project, seat.id, {previous_occupant, seat.occupant})
            self.store.save_project(project)
            return seat

    def remove_seat(self, project_id, seat_id):
        with self._lock:
            project = self.sinaxa.project(project_id)
            occupant = project.seat(seat_id).occupant
            self._drop_seat_conversations(project, seat_id, {occupant})
            seat, direct = project.remove_seat(seat_id)
            if direct:
                self.store.erase_session(project, direct)
            self.store.save_project(project)
            return seat

    def _drop_seat_conversations(self, project, seat_id, member_ids=()):
        for member_id in member_ids:
            self._reset_project_agent(project, member_id)
        for (project_id, _), talk in self._talks.items():
            if project_id == project.id:
                talk.conversations.pop(seat_id, None)

    # sessions ------------------------------------------------------------
    def add_session(self, project_id, name, participants):
        project = self.sinaxa.project(project_id)
        session = project.add_session(name, participants)
        self.store.save_project(project)
        return session

    def update_session(self, project_id, session_id, **fields):
        project, session = self.locate(project_id, session_id)
        previous_participants = set(session.participants)
        structural = {"name", "participants", "archived"}.intersection(fields)
        if session.kind != CUSTOM and structural:
            raise ModelError("direct and team sessions are managed by the project")
        if "turn_timeout" in fields:
            value = int(fields["turn_timeout"])
            if not 30 <= value <= 7200:
                raise ModelError(
                    "agent timeout must be between 30 and 7200 seconds")
            session.turn_timeout = value
        if "max_agent_turns" in fields:
            value = int(fields["max_agent_turns"])
            if not 1 <= value <= 100:
                raise ModelError(
                    "maximum agent turns must be between 1 and 100")
            session.max_agent_turns = value
        if "name" in fields:
            if not fields["name"].strip():
                raise ModelError("a session needs a name")
            session.name = fields["name"].strip()
        if "participants" in fields:
            participants = list(dict.fromkeys(fields["participants"]))
            if not participants:
                raise ModelError("a session needs at least one seat")
            for seat_id in participants:
                project.seat(seat_id)
            session.participants = participants
        if "archived" in fields:
            session.archived = bool(fields["archived"])
        if previous_participants != set(session.participants):
            affected = previous_participants | set(session.participants)
            for member_id in {project.seat(seat_id).occupant
                              for seat_id in affected}:
                self._reset_project_agent(project, member_id)
        self.store.save_project(project)
        return session

    def remove_session(self, project_id, session_id):
        project = self.sinaxa.project(project_id)
        session = project.remove_session(session_id)
        member_ids = {project.seat(seat_id).occupant
                      for seat_id in session.participants}
        talk = self._talks.pop((project.id, session.id), None)
        if talk:
            talk.stop()
        self.store.erase_session(project, session)
        self.store.forget_agent_session(project, session.id)
        for member_id in member_ids:
            self._reset_project_agent(project, member_id)
        self.store.save_project(project)
        return session

    def clear_context(self, project_id, session_id):
        project, session = self.locate(project_id, session_id)
        return self.talk(project, session).clear_context()

    def clear_history(self, project_id, session_id):
        project, session = self.locate(project_id, session_id)
        if any(job["project"] == project.id and job["session"] == session.id
               and not job["future"].done() for job in self._jobs.values()):
            raise ModelError("wait for the current agent round to finish")
        talk = self._talks.pop((project.id, session.id), None)
        if talk:
            talk.stop()
        member_ids = {project.seat(seat_id).occupant
                      for seat_id in session.participants}
        self.store.clear_history(project, session)
        session.seq = 0
        session.context_start_seq = 0
        session.last_activity_at = None
        for member_id in member_ids:
            self._reset_project_agent(project, member_id)
        self.store.save_project(project)

    # talking -------------------------------------------------------------
    def say(self, project_id, session_id, text, images=None):
        project, session = self.locate(project_id, session_id)
        if not project.is_open:
            raise ModelError("open the project before sending a message")
        if session.archived:
            raise ModelError("restore the session before sending a message")
        stored = [self.store.save_image(project, session, blob, suffix)
                  for blob, suffix in (images or [])]
        talk = self.talk(project, session)
        message = talk.post(text, images=stored)
        job_id = "job_" + uuid.uuid4().hex[:12]
        future = self._executor.submit(talk.run_turn, message)
        self._jobs[job_id] = {"project": project.id, "session": session.id,
                              "future": future, "created": message["ts"]}
        return message, job_id

    def _wait_project(self, project_id):
        for job in list(self._jobs.values()):
            if job["project"] == project_id:
                try:
                    job["future"].result()
                except Exception:
                    pass

    def image(self, project_id, session_id, name):
        project, session = self.locate(project_id, session_id)
        return self.store.image_path(project, session, name)

    def job(self, job_id):
        record = self._jobs.get(job_id)
        if not record:
            raise ModelError("no such turn")
        future = record["future"]
        return {"id": job_id, "done": future.done(),
                "error": str(future.exception()) if future.done() and future.exception() else None}

    # read model ----------------------------------------------------------
    def state(self, project_id=None, session_id=None, search=None,
              before=None, limit=60):
        projects = []
        for project in self.sinaxa.projects:
            projects.append({"id": project.id, "name": project.name,
                             "cwd": project.cwd, "state": project.state,
                             "type_id": project.type_id,
                             "storage": self.store.storage(project),
                             "sessions": [dict(session.as_dict(),
                                storage=self.store.storage(project, session))
                                for session in project.sessions]})
        out = {"engines": [describe(e) for e in self.sinaxa.engines],
               "members": [m.as_dict() for m in self.sinaxa.members],
               "seat_templates": [t.as_dict()
                                  for t in self.sinaxa.seat_templates],
               "project_types": [t.as_dict()
                                 for t in self.sinaxa.project_types],
               "projects": projects,
               "lead": self.sinaxa.lead.as_dict() if self.sinaxa.lead else None}
        if not self.sinaxa.projects:
            return out
        project = self.sinaxa.project(project_id) if project_id else self.sinaxa.projects[0]
        session = project.session(session_id) if session_id else project.team_session
        page = self.store.message_page(project, session, before=before,
                                       limit=limit, search=search)
        talk = self._talks.get((project.id, session.id))
        out.update({"project": project.id, "session": session.id,
                    "seats": [dict(seat.as_dict(),
                       name=self.sinaxa.seat_name(project, seat),
                       trouble=self.sinaxa.seat_trouble(project, seat))
                       for seat in project.seats],
                    "messages": page["messages"],
                    "message_page": {key: value for key, value in page.items()
                                     if key != "messages"},
                    "status": talk.status() if talk else {
                        "busy": [], "agents": [],
                        "engines": self.runtimes.status(project.id)}})
        return out

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        for talk in self._talks.values():
            talk.stop()
        self.runtimes.stop()
        self._executor.shutdown(wait=True, cancel_futures=False)


__all__ = ["App", "ModelError"]
