"""Project-scoped ownership and limits for local engine adapters."""

from .catalog import (CAPABILITIES, CLAUDE, CODEX, OPENCODE, describe)
from .limited_agent import LimitedAgent
from .manager import RuntimeManager
from .project_engines import ProjectEngines

__all__ = ["CAPABILITIES", "CLAUDE", "CODEX", "LimitedAgent", "OPENCODE",
           "ProjectEngines", "RuntimeManager", "describe"]
