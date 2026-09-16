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
