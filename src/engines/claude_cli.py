"""Claude over the CLI, one process per conversation.

There is no other shape available: a `claude` process is bound to one
session for its lifetime, and there is no server mode. So N conversations
cost N processes. `--resume` is used only to come back after a restart or a
death, never per message.
"""

import os


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
        """Every agent here owns a process. Stop them all, keep none."""
        agents, self._agents = self._agents, []
        for agent in agents:
            agent.stop()

    def agent(self, name, model=None, instructions=None, effort=None):
        from .claude_agent import ClaudeAgent

        a = ClaudeAgent(self, name, model, instructions, effort)
        self._agents.append(a)
        return a


from .claude_agent import ClaudeAgent  # compatibility export
