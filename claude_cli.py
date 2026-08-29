"""Claude over the CLI, one process per conversation.

There is no other shape available: a `claude` process is bound to one
session for its lifetime, and there is no server mode. So N conversations
cost N processes. `--resume` is used only to come back after a restart or a
death, never per message.
"""

import os
import subprocess
import threading

from claude_session import ClaudeSession, SessionDied, TurnTimedOut

READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]


def _rss_kb(pid):
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0


class ClaudeBackend:
    label = "claude cli"
    can_resume = True

    def __init__(self, cwd=None, binary="claude"):
        self.cwd = cwd or os.getcwd()
        self.binary = binary
        self._agents = []

    @property
    def alive(self):
        return any(a.session.alive for a in self._agents)

    @property
    def pids(self):
        return [a.session.pid for a in self._agents if a.session.pid]

    def start(self):
        return self

    def stop(self):
        for a in self._agents:
            a.stop()

    def agent(self, name, model=None, instructions=None):
        a = ClaudeAgent(self, name, model, instructions)
        self._agents.append(a)
        return a


class ClaudeAgent:
    provider = "claude-cli"

    def __init__(self, backend, name, model=None, instructions=None):
        self.backend = backend
        self.name = name
        self.model = model
        self.session = ClaudeSession(cwd=backend.cwd, binary=backend.binary,
                                     model=model, instructions=instructions,
                                     allowed_tools=READ_ONLY_TOOLS)
        self._lock = threading.Lock()

    def ask(self, text, timeout=600):
        with self._lock:
            try:
                return self.session.ask(text, timeout=timeout)
            except (SessionDied, TurnTimedOut) as exc:
                # the process is gone; --resume brings the context back
                self.session.activity = ""
                try:
                    self.session.start(resume=bool(self.session.session_id))
                    return self.session.ask(text, timeout=timeout)
                except Exception as exc2:
                    return None, {"error": "%s (and the retry failed: %s)"
                                           % (exc, exc2)}
            except Exception as exc:
                self.session.activity = ""
                return None, {"error": str(exc)[:400]}

    def status(self):
        pid = self.session.pid
        return {"provider": self.provider, "model": self.model or "default",
                "conversation": (self.session.session_id or "")[:8],
                "activity": self.session.activity, "turns": self.session.turns,
                "tokens": self.session.tokens, "alive": self.session.alive,
                "pids": [pid] if pid else [], "rss_kb": _rss_kb(pid) if pid else 0,
                "shared_process": False}

    def stop(self):
        self.session.stop()
