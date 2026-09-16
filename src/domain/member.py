from .constants import AGENT, HUMAN
from .errors import ModelError
from .identity import new_id


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
