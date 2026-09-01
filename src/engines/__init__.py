"""Engines: everything that knows how a provider is started.

An engine describes its own Member form, so adding a fourth one changes
nothing above this package. The three differ in ways that matter to the
person filling in that form, and the differences are measured, not guessed
(docs/design/03-providers.md):

    claude    one process per conversation. Model and effort are flags, so
              every seat may have its own.
    codex     one process hosting many threads, plus a small helper per
              thread. Reasoning effort is a config key read at process
              start, so it is the same for every seat -- medium, for now.
    opencode  one HTTP server hosting many sessions. It does not have a
              model list of its own: it brokers whatever its config
              declares, so sinaxa asks it and shows the answer. Effort is a
              property of the model there, not of the call.
"""

CLAUDE, CODEX, OPENCODE = "claude", "codex", "opencode"

DESCRIPTIONS = {
    CLAUDE: {
        "id": CLAUDE,
        "label": "Claude CLI",
        "binary_default": "claude",
        "models": ["sonnet", "opus", "haiku", "fable"],
        "models_are_a_hint": True,        # a full model name is fine too
        "models_from_engine": False,
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "effort_default": "medium",
        "note": "One process per seat, around 430 MB each.",
    },
    CODEX: {
        "id": CODEX,
        "label": "Codex",
        "binary_default": "codex",
        "models": [],
        "models_are_a_hint": True,
        "models_from_engine": False,
        "efforts": ["medium"],
        "effort_default": "medium",
        "note": "Effort is set when the process starts, so it is the same "
                "for every codex seat. Fixed at medium for now.",
    },
    OPENCODE: {
        "id": OPENCODE,
        "label": "opencode",
        "binary_default": "opencode",
        "models": [],
        "models_are_a_hint": False,       # pick from the list, nothing else
        "models_from_engine": True,
        "efforts": [],
        "effort_default": None,
        "note": "Models come from opencode's own configuration. sinaxa only "
                "lets you choose among them.",
    },
}

CODEX_EFFORT = "medium"


def describe(engine=None):
    if engine is None:
        return [DESCRIPTIONS[name] for name in (CLAUDE, CODEX, OPENCODE)]
    if engine not in DESCRIPTIONS:
        raise KeyError("no engine called %r" % engine)
    return DESCRIPTIONS[engine]


class Engines:
    """Holds the live backends, one per engine, started on first use.

    A backend is shared: every codex seat is a thread in one process, every
    opencode seat a session in one server. Claude has no backend to share --
    its adapter spawns a process per conversation, because it cannot do
    anything else.
    """

    def __init__(self, cwd, binaries=None, opencode_port=4096):
        self.cwd = cwd
        self.binaries = dict(binaries or {})
        self.opencode_port = opencode_port
        self._backends = {}

    def binary_for(self, engine, member_binary=None):
        return (member_binary or self.binaries.get(engine)
                or DESCRIPTIONS[engine]["binary_default"])

    def backend(self, engine, binary=None):
        key = (engine, binary or "")
        if key in self._backends:
            return self._backends[key]
        path = self.binary_for(engine, binary)
        if engine == CLAUDE:
            from .claude_cli import ClaudeBackend
            backend = ClaudeBackend(cwd=self.cwd, binary=path)
        elif engine == CODEX:
            from .codex_app import CodexAppBackend
            backend = CodexAppBackend(cwd=self.cwd, binary=path)
        elif engine == OPENCODE:
            from .opencode_http import OpencodeBackend
            backend = OpencodeBackend(port=self.opencode_port, cwd=self.cwd,
                                      binary=path)
        else:
            raise KeyError("no engine called %r" % engine)
        self._backends[key] = backend
        return backend

    def agent(self, member, name, instructions):
        """One live conversation for one seat."""
        backend = self.backend(member.engine, member.binary)
        kw = {"model": member.model, "instructions": instructions}
        if member.engine == CLAUDE:
            kw["effort"] = member.effort
        return backend.agent(name, **kw)

    def models_for(self, engine, binary=None):
        """What this engine can be asked for right now.

        Only opencode can answer for itself; for the other two the list is
        what we know, and a name typed by hand is equally valid.
        """
        description = DESCRIPTIONS[engine]
        if not description["models_from_engine"]:
            return list(description["models"])
        try:
            backend = self.backend(engine, binary)
            backend.start()
            return ["%s/%s" % pair for pair in backend.models()]
        except Exception:
            return []

    def stop(self):
        for backend in self._backends.values():
            try:
                backend.stop()
            except Exception:
                pass
        self._backends.clear()

    def status(self):
        live = []
        for (engine, _), backend in self._backends.items():
            live.append({"engine": engine, "label": backend.label,
                         "alive": bool(getattr(backend, "alive", False)),
                         "pids": list(getattr(backend, "pids", []))})
        return live
