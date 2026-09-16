import re

from .constants import AGENT, PALETTE
from .errors import ModelError
from .member import Member
from .project import Project
from .project_type import ProjectType
from .seat_template import SeatTemplate


class Sinaxa:
    """Workspace aggregate and cross-project invariants."""

    def __init__(self, engines=None, members=None, projects=None,
                 seat_templates=None, project_types=None):
        self.engines = list(engines or [])
        self.members = list(members or [])
        self.projects = list(projects or [])
        self.seat_templates = list(seat_templates or [])
        self.project_types = list(project_types or [])

    def _find(self, values, object_id, message):
        for value in values:
            if value.id == object_id:
                return value
        raise ModelError(message)

    def engine(self, engine_id):
        return self._find(self.engines, engine_id, "no such engine")

    def member(self, member_id):
        return self._find(self.members, member_id, "no such member")

    def project(self, project_id):
        return self._find(self.projects, project_id, "no such project")

    def seat_template(self, template_id):
        return self._find(self.seat_templates, template_id,
                          "no such seat template")

    def project_type(self, type_id):
        return self._find(self.project_types, type_id, "no such project type")

    @property
    def lead(self):
        return next((member for member in self.members if member.is_human), None)

    def add_member(self, **fields):
        name = fields.get("name", "")
        if any(member.name.casefold() == name.strip().casefold()
               for member in self.members):
            raise ModelError("member names must be unique")
        if fields.get("kind", AGENT) == AGENT:
            engine = self.engine(fields.get("engine"))
            if not engine.enabled:
                raise ModelError("that engine is disabled")
        elif any(member.is_human for member in self.members):
            raise ModelError("there can only be one human lead")
        member = Member(**fields)
        used = {existing.colour for existing in self.members}
        member.colour = member.colour or next(
            (colour for colour in PALETTE if colour not in used),
            PALETTE[len(self.members) % len(PALETTE)])
        self.members.append(member)
        return member

    def update_member(self, member_id, **fields):
        member = self.member(member_id)
        if "name" in fields:
            name = fields["name"].strip()
            if not name:
                raise ModelError("a member needs a name")
            if any(existing.id != member.id
                   and existing.name.casefold() == name.casefold()
                   for existing in self.members):
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
        if any(seat.occupant == member_id
               for project in self.projects for seat in project.seats):
            raise ModelError("that member still occupies a seat")
        if any(template.default_agent == member_id
               for template in self.seat_templates):
            raise ModelError(
                "that member is still a default agent for a seat template")
        self.members.remove(member)
        return member

    def add_project(self, name, cwd=None, type_id=None):
        if any(project.name.casefold() == name.strip().casefold()
               for project in self.projects):
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

    def add_project_seat(self, project_id, template_id, occupant=None,
                         prompt=None):
        project = self.project(project_id)
        template = self.seat_template(template_id)
        if occupant:
            self.member(occupant)
        return project.add_seat(template.role, prompt or template.prompt,
                                occupant, template_id=template.id)

    def add_seat_template(self, **fields):
        role = fields.get("role", "")
        if any(template.role.casefold() == role.strip().casefold()
               for template in self.seat_templates):
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
        if any(existing.id != template.id
               and existing.role.casefold() == role.casefold()
               for existing in self.seat_templates):
            raise ModelError("seat template roles must be unique")
        self._validate_default_agent(candidate.get("default_agent"))
        replacement = SeatTemplate.from_dict(candidate)
        self.seat_templates[self.seat_templates.index(template)] = replacement
        return replacement

    def remove_seat_template(self, template_id):
        template = self.seat_template(template_id)
        if any(template_id in project_type.seat_templates
               for project_type in self.project_types):
            raise ModelError(
                "that seat template is still used by a project type")
        if any(seat.template_id == template_id
               for project in self.projects for seat in project.seats):
            raise ModelError(
                "that seat definition is still used by a project")
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
        if any(project_type.name.casefold() == name.strip().casefold()
               for project_type in self.project_types):
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
        if any(existing.id != project_type.id
               and existing.name.casefold() == name.casefold()
               for existing in self.project_types):
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
