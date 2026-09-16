from .errors import ModelError
from .identity import new_id


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
