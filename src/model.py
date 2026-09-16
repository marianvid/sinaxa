"""Compatibility facade for the provider-independent domain package.

New code should import from :mod:`src.domain`. Existing integrations may keep
using ``src.model`` while the public API remains stable.
"""

from .domain import *  # noqa: F401,F403
from .domain import __all__
