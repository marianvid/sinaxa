from .errors import ModelError
from .identity import new_id


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
