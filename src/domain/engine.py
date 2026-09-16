from .errors import ModelError


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
