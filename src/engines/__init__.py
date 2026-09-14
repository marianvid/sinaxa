"""Engine contracts and project-scoped runtime ownership."""

import threading

CLAUDE, CODEX, OPENCODE = "claude", "codex", "opencode"

CAPABILITIES = {
    CLAUDE: {"label": "Claude CLI", "models": ["sonnet", "opus", "haiku"],
             "efforts": ["low", "medium", "high", "max"],
             "accepts_custom_model": True},
    CODEX: {"label": "Codex CLI", "models": [],
            "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
            "accepts_custom_model": True},
    OPENCODE: {"label": "OpenCode CLI", "models": [], "efforts": [],
               "accepts_custom_model": True},
}


class LimitedAgent:
    """Apply an engine-wide concurrency limit without changing adapters."""
    def __init__(self, agent, semaphore, after_turn=None, resume_mode=False):
        self._agent = agent
        self._semaphore = semaphore
        self._after_turn = after_turn
        self._resume_mode = resume_mode
        self._native_id = None
        self.resumed = False

    def __getattr__(self, name):
        return getattr(self._agent, name)

    def ask(self, *args, **kwargs):
        with self._semaphore:
            if self._resume_mode and self._native_id:
                self.resume(self._native_id)
            answer = self._agent.ask(*args, **kwargs)
            if self._after_turn:
                self._after_turn(self)
            if self._resume_mode:
                self._native_id = self.native_id()
                self._agent.stop()
            return answer

    def stop(self):
        return self._agent.stop()

    def resume(self, native_id):
        resume = getattr(self._agent, "resume", None)
        succeeded = bool(resume and resume(native_id))
        if succeeded:
            self._native_id = native_id
        return succeeded

    def native_id(self):
        return (getattr(self._agent, "thread_id", None)
                or getattr(self._agent, "session_id", None)
                or getattr(getattr(self._agent, "session", None),
                           "session_id", None) or self._native_id)


class ProjectEngines:
    """All live providers for one project; nothing starts in __init__."""
    def __init__(self, project, configs, port_offset=0, checkpoint=None):
        self.project = project
        self.configs = {config.id: config for config in configs}
        self.port_offset = port_offset
        self.checkpoint = checkpoint
        self._backends = {}
        self._limits = {config.id: threading.BoundedSemaphore(
            config.max_concurrency) for config in configs}

    def config(self, engine_id):
        config = self.configs.get(engine_id)
        if not config or not config.enabled:
            raise RuntimeError("engine %s is unavailable" % engine_id)
        return config

    def backend(self, engine_id):
        if engine_id in self._backends:
            return self._backends[engine_id]
        config = self.config(engine_id)
        binary = config.executable or config.kind
        if config.kind == CLAUDE:
            from .claude_cli import ClaudeBackend
            backend = ClaudeBackend(cwd=self.project.cwd, binary=binary)
        elif config.kind == CODEX:
            from .codex_app import CodexAppBackend
            backend = CodexAppBackend(cwd=self.project.cwd, binary=binary)
        elif config.kind == OPENCODE:
            from .opencode_http import OpencodeBackend
            base = int(config.options.get("base_port", 4096))
            backend = OpencodeBackend(port=base + self.port_offset,
                                      cwd=self.project.cwd, binary=binary)
        else:
            raise RuntimeError("unknown engine kind %s" % config.kind)
        self._backends[engine_id] = backend
        return backend

    def agent(self, member, name, instructions, native_id=None):
        config = self.config(member.engine)
        backend = self.backend(member.engine)
        values = {"model": member.model, "instructions": instructions}
        if config.kind == CLAUDE:
            values["effort"] = member.effort
        agent = LimitedAgent(backend.agent(name, **values),
                             self._limits[config.id], self.checkpoint,
                             resume_mode=config.mode == "resume")
        if native_id:
            try:
                agent.resumed = agent.resume(native_id)
            except Exception:
                agent.resumed = False
        return agent

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
        for backend in list(self._backends.values()):
            try:
                backend.stop()
            except Exception:
                pass
        self._backends.clear()


class RuntimeManager:
    """Lazily owns one independent engine set per logically open project."""
    def __init__(self, sinaxa, factory=None):
        self.sinaxa = sinaxa
        self.factory = factory
        self._projects = {}

    def for_project(self, project, checkpoint=None):
        if not project.is_open:
            raise RuntimeError("project is closed")
        if project.id not in self._projects:
            if self.factory:
                runtime = self.factory(project)
            else:
                index = sorted(p.id for p in self.sinaxa.projects).index(project.id)
                runtime = ProjectEngines(project, self.sinaxa.engines,
                                         port_offset=index, checkpoint=checkpoint)
            self._projects[project.id] = runtime
        return self._projects[project.id]

    def close(self, project_id):
        runtime = self._projects.pop(project_id, None)
        if runtime:
            runtime.stop()

    def status(self, project_id):
        runtime = self._projects.get(project_id)
        return runtime.status() if runtime else []

    def stop(self):
        for project_id in list(self._projects):
            self.close(project_id)


def describe(config):
    out = config.as_dict()
    out.update(CAPABILITIES.get(config.kind, {}))
    return out


__all__ = ["CLAUDE", "CODEX", "OPENCODE", "ProjectEngines",
           "RuntimeManager", "describe"]
