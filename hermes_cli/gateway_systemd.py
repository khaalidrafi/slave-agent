"""Does this process have an elevation path for the system-scope gateway unit?

Split out of the deleted ``hermes_cli/update_cmd_fleet.py`` (FORK.org P0), which asked the
same question before restarting fleet units. The remaining consumer is the dashboard's
gateway lifecycle action (``hermes_cli/web_server_gateway.py``): a system-scope verb spawned
as the dashboard's own user can only ever log "requires root", so the action elevates -- but
only when it can prove it will not prompt.

``gateway.py`` owns the decision that a system verb needs root at all
(``_require_root_for_system_service``); this module owns only the "can I get it, silently"
question, which is a property of the host's sudoers, not of the CLI.
"""

from __future__ import annotations

import os
import subprocess


def needs_sudo(scope: str) -> bool:
    """True when managing units in *scope* requires elevation on this host."""
    return (
        scope == "system"
        and hasattr(os, "geteuid")
        and os.geteuid() != 0  # windows-footgun: ok — systemd path, Linux-only
    )


def sudo_noninteractive_ok(targeted_probe: list) -> bool:
    """True when this user can elevate without a prompt.

    ``sudo -n true`` first; a refusal is inconclusive because a NOPASSWD sudoers entry scoped
    to one command (the hardened shape) rejects the blanket probe, so fall back to running
    ``sudo -n <targeted_probe>`` — callers pass a non-destructive stand-in for the argv they
    are about to elevate.
    """
    try:
        if subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5).returncode == 0:
            return True
        # Blanket sudo refused — a targeted NOPASSWD sudoers entry may still work.
        return subprocess.run(["sudo", "-n", *targeted_probe], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
