import subprocess
import threading

from .claude_errors import SessionDied, TurnTimedOut
from .claude_session import ClaudeSession

READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]


def _rss_kb(pid):
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0


class ClaudeAgent:
    provider = "claude-cli"
    accepts_images = True

    def __init__(self, backend, name, model=None, instructions=None,
                 effort=None):
        self.backend = backend
        self.name = name
        self.model = model
        self.effort = effort
        self.session = ClaudeSession(cwd=backend.cwd, binary=backend.binary,
                                     model=model, instructions=instructions,
                                     allowed_tools=READ_ONLY_TOOLS,
                                     effort=effort)
        self._lock = threading.Lock()

    def ask(self, text, timeout=600, images=()):
        with self._lock:
            try:
                return self.session.ask(text, timeout=timeout, images=images)
            except (SessionDied, TurnTimedOut) as exc:
                self.session.activity = ""
                try:
                    self.session.start(resume=bool(self.session.session_id))
                    return self.session.ask(text, timeout=timeout, images=images)
                except Exception as retry_error:
                    return None, {"error": "%s (and the retry failed: %s)"
                                           % (exc, retry_error)}
            except Exception as exc:
                self.session.activity = ""
                return None, {"error": str(exc)[:400]}

    def resume(self, session_id):
        if not session_id:
            return False
        self.session.session_id = session_id
        self.session.turns = 1
        return True

    def status(self):
        pid = self.session.pid
        return {"provider": self.provider, "model": self.model or "default",
                "conversation": (self.session.session_id or "")[:8],
                "activity": self.session.activity, "turns": self.session.turns,
                "tokens": self.session.tokens, "alive": self.session.alive,
                "pids": [pid] if pid else [],
                "rss_kb": _rss_kb(pid) if pid else 0,
                "shared_process": False}

    def stop(self):
        self.session.stop()
        if self in self.backend._agents:
            self.backend._agents.remove(self)
