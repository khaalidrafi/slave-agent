"""Resolve SLAVE_HOME for standalone skill scripts.

Skill scripts may run outside the slave-agent process (e.g. system Python,
nix env, CI) where ``slave_constants`` is not importable.  This module
provides the same ``get_slave_home()`` and ``display_slave_home()``
contracts as ``slave_constants`` without requiring it on ``sys.path``.

When ``slave_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``slave_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``SLAVE_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from slave_constants import display_slave_home as display_slave_home
    from slave_constants import get_slave_home as get_slave_home
except (ModuleNotFoundError, ImportError):

    def get_slave_home() -> Path:
        """Return the slave-agent home directory (default: ~/.slave).

        Mirrors ``slave_constants.get_slave_home()``."""
        val = os.environ.get("SLAVE_HOME", "").strip()
        return Path(val) if val else Path.home() / ".slave"

    def display_slave_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``slave_constants.display_slave_home()``."""
        home = get_slave_home()
        try:
            return "~/" + home.relative_to(Path.home()).as_posix()
        except ValueError:
            return str(home)
