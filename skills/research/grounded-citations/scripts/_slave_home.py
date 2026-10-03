"""Resolve SLAVE_HOME for standalone skill scripts.

Skill scripts may run outside the slave-agent process (system Python, nix env,
CI) where ``slave_constants`` is not importable.  This module provides the
same ``get_slave_home()`` contract without requiring it on ``sys.path``.

When ``slave_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from slave_constants import get_slave_home as get_slave_home
except (ModuleNotFoundError, ImportError):

    def get_slave_home() -> Path:
        """Return the slave-agent home directory (default: ``~/.slave``)."""
        val = os.environ.get("SLAVE_HOME", "").strip()
        return Path(val) if val else Path.home() / ".slave"
