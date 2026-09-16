from .errors import ModelError
from .identity import new_id


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
