import threading

from .catalog import CAPABILITIES, CLAUDE, CODEX, OPENCODE
from .limited_agent import LimitedAgent


class ProjectEngines:
    """All live providers for one project; nothing starts in __init__."""

    def __init__(self, project, configs, port_offset=0, checkpoint=None):
        self.project = project
        self.configs = {config.id: config for config in configs}
        self.port_offset = port_offset
        self.checkpoint = checkpoint
        self._backends = {}
        self._agents = {}
        self._agent_locks = {}
        self._lock = threading.RLock()
        self._limits = {config.id: threading.BoundedSemaphore(
            config.max_concurrency) for config in configs}

    def config(self, engine_id):
        config = self.configs.get(engine_id)
        if not config or not config.enabled:
            raise RuntimeError("engine %s is unavailable" % engine_id)
        if config.mode != "persistent":
            raise RuntimeError("non-persistent engine mode is not yet implemented")
        return config

    def backend(self, engine_id):
        if engine_id in self._backends:
            return self._backends[engine_id]
        config = self.config(engine_id)
        binary = config.executable or config.kind
        if config.kind == CLAUDE:
            from ..engines.claude_cli import ClaudeBackend
            backend = ClaudeBackend(cwd=self.project.cwd, binary=binary)
        elif config.kind == CODEX:
            from ..engines.codex_app import CodexAppBackend
            backend = CodexAppBackend(cwd=self.project.cwd, binary=binary)
        elif config.kind == OPENCODE:
            from ..engines.opencode_http import OpencodeBackend
            base = int(config.options.get("base_port", 4096))
            backend = OpencodeBackend(port=base + self.port_offset,
                                      cwd=self.project.cwd, binary=binary)
        else:
            raise RuntimeError("unknown engine kind %s" % config.kind)
        self._backends[engine_id] = backend
        return backend

    def agent(self, member, name, instructions, native_id=None):
        with self._lock:
            if member.id in self._agents:
                return self._agents[member.id]
            config = self.config(member.engine)
            backend = self.backend(member.engine)
            values = {"model": member.model, "instructions": instructions}
            if config.kind == CLAUDE:
                values["effort"] = member.effort
            agent = LimitedAgent(backend.agent(name, **values),
                                 self._limits[config.id], self.checkpoint)
            if native_id:
                try:
                    agent.resumed = agent.resume(native_id)
                except Exception:
                    agent.resumed = False
            self._agents[member.id] = agent
            self._agent_locks.setdefault(member.id, threading.RLock())
            return agent

    def agent_lock(self, member_id):
        with self._lock:
            return self._agent_locks.setdefault(member_id, threading.RLock())

    def has_agent(self, member_id):
        with self._lock:
            return member_id in self._agents

    def is_current(self, member_id, agent):
        return self._agents.get(member_id) is agent

    def reset_agent(self, member_id):
        with self._lock:
            agent = self._agents.pop(member_id, None)
        if agent:
            try:
                agent.stop()
            except Exception:
                pass

    def models_for(self, engine_id):
        config = self.config(engine_id)
        if config.kind != OPENCODE:
            return list(CAPABILITIES[config.kind]["models"])
        try:
            backend = self.backend(engine_id)
            backend.start()
            return ["%s/%s" % pair for pair in backend.models()]
        except Exception:
            return []

    def status(self):
        return [{"engine": key, "label": backend.label,
                 "alive": bool(getattr(backend, "alive", False)),
                 "pids": list(getattr(backend, "pids", []))}
                for key, backend in self._backends.items()]

    def stop(self):
        for member_id in list(self._agents):
            self.reset_agent(member_id)
        for backend in list(self._backends.values()):
            try:
                backend.stop()
            except Exception:
                pass
        self._backends.clear()
        self._agent_locks.clear()
