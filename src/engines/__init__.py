"""Compatibility facade for engine runtime ownership.

Provider adapters live in this package; lifecycle and concurrency policy live
in :mod:`src.runtime`.
"""

from ..runtime import (CAPABILITIES, CLAUDE, CODEX, OPENCODE, LimitedAgent,
                       ProjectEngines, RuntimeManager, describe)

__all__ = ["CAPABILITIES", "CLAUDE", "CODEX", "LimitedAgent", "OPENCODE",
           "ProjectEngines", "RuntimeManager", "describe"]
