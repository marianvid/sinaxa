from .constants import (CUSTOM, DEFAULT_MAX_AGENT_TURNS,
                        DEFAULT_TURN_TIMEOUT, DIRECT, TEAM)
from .errors import ModelError
from .identity import new_id


class Session:
    """One conversation with a chosen set of project seats."""

    def __init__(self, name, participants=None, kind=CUSTOM, id=None, seq=0,
                 context_start_seq=0, archived=False, created_at=None,
                 last_activity_at=None, turn_timeout=DEFAULT_TURN_TIMEOUT,
                 max_agent_turns=DEFAULT_MAX_AGENT_TURNS):
        if kind not in (DIRECT, TEAM, CUSTOM):
            raise ModelError("unknown session kind")
        if kind == CUSTOM and not (name or "").strip():
            raise ModelError("a session needs a name")
        self.id = id or new_id("ses")
        self.name = (name or "").strip()
        self.participants = list(dict.fromkeys(participants or []))
        self.kind = kind
        self.seq = int(seq)
        self.context_start_seq = int(context_start_seq)
        self.archived = bool(archived)
        self.created_at = created_at
        self.last_activity_at = last_activity_at
        self.turn_timeout = int(turn_timeout)
        self.max_agent_turns = int(max_agent_turns)
        if not 30 <= self.turn_timeout <= 7200:
            raise ModelError("agent timeout must be between 30 and 7200 seconds")
        if not 1 <= self.max_agent_turns <= 100:
            raise ModelError("maximum agent turns must be between 1 and 100")

    @property
    def managed(self):
        return self.kind in (DIRECT, TEAM)

    def as_dict(self):
        return {"id": self.id, "name": self.name,
                "participants": self.participants, "kind": self.kind,
                "seq": self.seq, "context_start_seq": self.context_start_seq,
                "archived": self.archived, "created_at": self.created_at,
                "last_activity_at": self.last_activity_at,
                "turn_timeout": self.turn_timeout,
                "max_agent_turns": self.max_agent_turns}

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)
