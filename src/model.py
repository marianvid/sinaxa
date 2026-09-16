"""Provider-agnostic domain objects.

Session is the only conversational object. It selects project seats and owns
an independent message history and context boundary. Engines describe local
CLI installations; members choose an engine; seats give members project roles.
"""

import re
import time
import uuid

HUMAN, AGENT = "human", "agent"
DIRECT, TEAM, CUSTOM = "direct", "team", "custom"
OPEN, CLOSED = "open", "closed"
DEFAULT_TURN_TIMEOUT = 1800
DEFAULT_MAX_AGENT_TURNS = 24

PALETTE = ["#2f6fd0", "#c96442", "#3fbf7f", "#7c6cf0", "#e0a53f",
           "#38a9a2", "#d05f9c", "#8a9a3b"]


def new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


class ModelError(Exception):
    """A domain rule was broken; its message is safe to show in the UI."""


class EngineConfig:
    """One globally configured local CLI installation."""

    def __init__(self, id, kind, name=None, enabled=True, executable=None,
                 mode="persistent", streaming=True, max_concurrency=4,
                 mcp_servers=None, options=None):
        if not id or not kind:
            raise ModelError("an engine needs an id and a kind")
        if mode not in ("persistent", "resume"):
            raise ModelError("engine mode must be persistent or resume")
        if int(max_concurrency) < 1:
            raise ModelError("engine concurrency must be at least one")
        self.id = id
        self.kind = kind
        self.name = name or kind
        self.enabled = bool(enabled)
        self.executable = executable
        self.mode = mode
        self.streaming = bool(streaming)
        self.max_concurrency = int(max_concurrency)
        self.mcp_servers = list(mcp_servers or [])
        self.options = dict(options or {})

    def as_dict(self):
        return {"id": self.id, "kind": self.kind, "name": self.name,
                "enabled": self.enabled, "executable": self.executable,
                "mode": self.mode, "streaming": self.streaming,
                "max_concurrency": self.max_concurrency,
                "mcp_servers": self.mcp_servers, "options": self.options}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class Member:
    """A reusable person or agent profile."""

    def __init__(self, name, kind=AGENT, engine=None, model=None, effort=None,
                 id=None, colour=None, options=None, allowed_mcp_servers=None):
        if not (name or "").strip():
            raise ModelError("a member needs a name")
        if kind == AGENT and not engine:
            raise ModelError("an agent needs an engine")
        self.id = id or new_id("mem")
        self.name = name.strip()
        self.kind = kind
        self.engine = engine
        self.model = model
        self.effort = effort
        self.colour = colour
        self.options = dict(options or {})
        self.allowed_mcp_servers = list(allowed_mcp_servers or [])

    @property
    def is_human(self):
        return self.kind == HUMAN

    def as_dict(self):
        return {"id": self.id, "name": self.name, "kind": self.kind,
                "engine": self.engine, "model": self.model,
                "effort": self.effort, "colour": self.colour,
                "options": self.options,
                "allowed_mcp_servers": self.allowed_mcp_servers}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class SeatTemplate:
    """A reusable role definition which can seed project seats."""

    def __init__(self, role, prompt, category="general", default_agent=None,
                 id=None):
        if not (role or "").strip():
            raise ModelError("a seat template needs a role")
        if not (prompt or "").strip():
            raise ModelError("a seat template needs a prompt")
        self.id = id or new_id("stp")
        self.role = role.strip()
        self.prompt = prompt.strip()
        self.category = (category or "general").strip()
        self.default_agent = default_agent or None

    def as_dict(self):
        return {"id": self.id, "role": self.role, "prompt": self.prompt,
                "category": self.category,
                "default_agent": self.default_agent}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class ProjectType:
    """A project recipe made from an ordered set of seat templates."""

    def __init__(self, name, category="general", description="",
                 seat_templates=None, id=None):
        if not (name or "").strip():
            raise ModelError("a project type needs a name")
        self.id = id or new_id("typ")
        self.name = name.strip()
        self.category = (category or "general").strip()
        self.description = (description or "").strip()
        self.seat_templates = list(dict.fromkeys(seat_templates or []))

    def as_dict(self):
        return {"id": self.id, "name": self.name,
                "category": self.category, "description": self.description,
                "seat_templates": self.seat_templates}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class Seat:
    """A project role occupied by a member."""

    def __init__(self, role, prompt, occupant=None, id=None, template_id=None):
        if not (role or "").strip():
            raise ModelError("a seat needs a role")
        if not (prompt or "").strip():
            raise ModelError("a seat needs a prompt")
        self.id = id or new_id("seat")
        self.role = role.strip()
        self.prompt = prompt
        self.occupant = occupant or None
        self.template_id = template_id or None

    def as_dict(self):
        return {"id": self.id, "role": self.role, "prompt": self.prompt,
                "occupant": self.occupant, "template_id": self.template_id}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


class Session:
    """One conversation with a chosen set of project seats."""

    def __init__(self, name, participants=None, kind=CUSTOM, id=None, seq=0,
                 context_start_seq=0, archived=False, created_at=None,
                 last_activity_at=None, turn_timeout=DEFAULT_TURN_TIMEOUT,
                 max_agent_turns=DEFAULT_MAX_AGENT_TURNS):
        if kind not in (DIRECT, TEAM, CUSTOM):
            raise ModelError("unknown session kind")
        if kind == CUSTOM and not (name or "").strip():
            raise ModelError("a session needs a name")
        self.id = id or new_id("ses")
        self.name = (name or "").strip()
        self.participants = list(dict.fromkeys(participants or []))
        self.kind = kind
        self.seq = int(seq)
        self.context_start_seq = int(context_start_seq)
        self.archived = bool(archived)
        self.created_at = created_at
        self.last_activity_at = last_activity_at
        self.turn_timeout = int(turn_timeout)
        self.max_agent_turns = int(max_agent_turns)
        if not 30 <= self.turn_timeout <= 7200:
            raise ModelError("agent timeout must be between 30 and 7200 seconds")
        if not 1 <= self.max_agent_turns <= 100:
            raise ModelError("maximum agent turns must be between 1 and 100")

    @property
    def managed(self):
        return self.kind in (DIRECT, TEAM)

    def as_dict(self):
        return {"id": self.id, "name": self.name,
                "participants": self.participants, "kind": self.kind,
                "seq": self.seq, "context_start_seq": self.context_start_seq,
                "archived": self.archived, "created_at": self.created_at,
                "last_activity_at": self.last_activity_at,
                "turn_timeout": self.turn_timeout,
                "max_agent_turns": self.max_agent_turns}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)


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
        if not any(s.kind == TEAM for s in self.sessions):
            self.sessions.insert(0, Session("Team", [], TEAM))

    @property
    def is_open(self):
        return self.state == OPEN

    @property
    def team_session(self):
        return next(s for s in self.sessions if s.kind == TEAM)

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
        return next((s for s in self.sessions
                     if s.kind == DIRECT and s.participants == [seat_id]), None)

    def add_seat(self, role, prompt, occupant=None, template_id=None):
        if any(s.role.casefold() == role.strip().casefold() for s in self.seats):
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


class Sinaxa:
    """Workspace aggregate and cross-project invariants."""

    def __init__(self, engines=None, members=None, projects=None,
                 seat_templates=None, project_types=None):
        self.engines = list(engines or [])
        self.members = list(members or [])
        self.projects = list(projects or [])
        self.seat_templates = list(seat_templates or [])
        self.project_types = list(project_types or [])

    def engine(self, engine_id):
        for engine in self.engines:
            if engine.id == engine_id:
                return engine
        raise ModelError("no such engine")

    def member(self, member_id):
        for member in self.members:
            if member.id == member_id:
                return member
        raise ModelError("no such member")

    def project(self, project_id):
        for project in self.projects:
            if project.id == project_id:
                return project
        raise ModelError("no such project")

    def seat_template(self, template_id):
        for template in self.seat_templates:
            if template.id == template_id:
                return template
        raise ModelError("no such seat template")

    def project_type(self, type_id):
        for project_type in self.project_types:
            if project_type.id == type_id:
                return project_type
        raise ModelError("no such project type")

    @property
    def lead(self):
        return next((member for member in self.members if member.is_human), None)

    def add_member(self, **fields):
        name = fields.get("name", "")
        if any(m.name.casefold() == name.strip().casefold() for m in self.members):
            raise ModelError("member names must be unique")
        if fields.get("kind", AGENT) == AGENT:
            engine = self.engine(fields.get("engine"))
            if not engine.enabled:
                raise ModelError("that engine is disabled")
        elif any(member.is_human for member in self.members):
            raise ModelError("there can only be one human lead")
        member = Member(**fields)
        used = {m.colour for m in self.members}
        member.colour = member.colour or next((c for c in PALETTE if c not in used),
                                               PALETTE[len(self.members) % len(PALETTE)])
        self.members.append(member)
        return member

    def update_member(self, member_id, **fields):
        member = self.member(member_id)
        if "name" in fields:
            name = fields["name"].strip()
            if not name:
                raise ModelError("a member needs a name")
            if any(m.id != member.id and m.name.casefold() == name.casefold()
                   for m in self.members):
                raise ModelError("member names must be unique")
        if "engine" in fields and fields["engine"]:
            engine = self.engine(fields["engine"])
            if not engine.enabled:
                raise ModelError("that engine is disabled")
        for key, value in fields.items():
            if hasattr(member, key):
                setattr(member, key, value)
        return member

    def remove_member(self, member_id):
        member = self.member(member_id)
        if member.is_human:
            raise ModelError("the human lead cannot be removed")
        if any(seat.occupant == member_id for p in self.projects for seat in p.seats):
            raise ModelError("that member still occupies a seat")
        if any(template.default_agent == member_id
               for template in self.seat_templates):
            raise ModelError("that member is still a default agent for a seat template")
        self.members.remove(member)
        return member

    def add_project(self, name, cwd=None, type_id=None):
        if any(p.name.casefold() == name.strip().casefold()
               for p in self.projects):
            raise ModelError("a project with that name already exists")
        project_type = self.project_type(type_id) if type_id else None
        project = Project(name, cwd=cwd, type_id=type_id)
        if project_type:
            for template_id in project_type.seat_templates:
                template = self.seat_template(template_id)
                project.add_seat(template.role, template.prompt,
                                 template.default_agent,
                                 template_id=template.id)
        self.projects.append(project)
        return project

    def add_seat_template(self, **fields):
        role = fields.get("role", "")
        if any(t.role.casefold() == role.strip().casefold()
               for t in self.seat_templates):
            raise ModelError("seat template roles must be unique")
        self._validate_default_agent(fields.get("default_agent"))
        template = SeatTemplate(**fields)
        self.seat_templates.append(template)
        return template

    def update_seat_template(self, template_id, **fields):
        template = self.seat_template(template_id)
        candidate = template.as_dict()
        candidate.update({key: value for key, value in fields.items()
                          if key in {"role", "prompt", "category",
                                     "default_agent"}})
        role = (candidate.get("role") or "").strip()
        if any(t.id != template.id and t.role.casefold() == role.casefold()
               for t in self.seat_templates):
            raise ModelError("seat template roles must be unique")
        self._validate_default_agent(candidate.get("default_agent"))
        replacement = SeatTemplate.from_dict(candidate)
        self.seat_templates[self.seat_templates.index(template)] = replacement
        return replacement

    def remove_seat_template(self, template_id):
        template = self.seat_template(template_id)
        if any(template_id in project_type.seat_templates
               for project_type in self.project_types):
            raise ModelError("that seat template is still used by a project type")
        self.seat_templates.remove(template)
        return template

    def _validate_default_agent(self, member_id):
        if member_id:
            member = self.member(member_id)
            if member.is_human:
                raise ModelError("a default agent cannot be the human lead")

    def _validate_type_templates(self, template_ids):
        for template_id in template_ids:
            self.seat_template(template_id)

    def add_project_type(self, **fields):
        name = fields.get("name", "")
        if any(t.name.casefold() == name.strip().casefold()
               for t in self.project_types):
            raise ModelError("project type names must be unique")
        self._validate_type_templates(fields.get("seat_templates", []))
        project_type = ProjectType(**fields)
        self.project_types.append(project_type)
        return project_type

    def update_project_type(self, type_id, **fields):
        project_type = self.project_type(type_id)
        candidate = project_type.as_dict()
        candidate.update({key: value for key, value in fields.items()
                          if key in {"name", "category", "description",
                                     "seat_templates"}})
        name = (candidate.get("name") or "").strip()
        if any(t.id != project_type.id and t.name.casefold() == name.casefold()
               for t in self.project_types):
            raise ModelError("project type names must be unique")
        self._validate_type_templates(candidate.get("seat_templates", []))
        replacement = ProjectType.from_dict(candidate)
        self.project_types[self.project_types.index(project_type)] = replacement
        return replacement

    def remove_project_type(self, type_id):
        project_type = self.project_type(type_id)
        if any(project.type_id == type_id for project in self.projects):
            raise ModelError("that project type is still used by a project")
        self.project_types.remove(project_type)
        return project_type

    def remove_project(self, project_id):
        project = self.project(project_id)
        self.projects.remove(project)
        return project

    def seat_name(self, project, seat):
        return self.member(seat.occupant).name if seat.occupant else "Unassigned"

    def seat_runs_engine(self, seat):
        """Whether a seat should receive an automated conversational turn."""
        if not seat.occupant:
            return False
        try:
            return not self.member(seat.occupant).is_human
        except ModelError:
            return True

    def seat_trouble(self, project, seat):
        if not seat.occupant:
            return "this seat has no agent"
        try:
            member = self.member(seat.occupant)
            if member.is_human:
                return None
            engine = self.engine(member.engine)
        except ModelError as exc:
            return str(exc)
        return None if engine.enabled else "%s is disabled" % engine.name

    def mentioned(self, project, text, seats):
        found = []
        for seat in seats:
            if not self.seat_runs_engine(seat):
                continue
            member = self.member(seat.occupant)
            if any(re.search(r"(?<![\w@])@%s\b" % re.escape(name), text,
                             re.IGNORECASE)
                   for name in (member.name, seat.role)):
                found.append(seat)
        return found
