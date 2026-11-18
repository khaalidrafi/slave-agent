"""Resolved-home test for agent.redact's ``config.yaml`` secret-file detection (moved out unchanged)."""

import os


def _is_under_slave_home(path: str) -> bool:
    """True when an absolute ``config.yaml`` path sits under the active slave-agent home or root.

    The default home's basename is an installation detail — ``.slave`` on POSIX, ``slave``
    under ``AppData/Local`` on Windows — and a resolved path never spells ``$SLAVE_HOME``,
    so the literal-segment test in ``_is_secret_file_arg`` cannot see a native Windows path.
    Compare against the resolved homes instead. Only reached for a ``config.yaml`` basename,
    so the resolve cost stays off the per-token command scan.
    """
    from agent.file_safety import _slave_dirs
    from tools.environments.sandbox_scope import sandbox_lexical_path
    # A hosted path names a file in the sandbox: judged as written (never empty), not resolved on this host.
    try:
        target = os.path.normcase(sandbox_lexical_path(path) or os.path.realpath(os.path.expanduser(path)))
    except (OSError, ValueError):
        return False
    for home in _slave_dirs():
        try:
            base = os.path.normcase(os.path.realpath(str(home)))
        except (OSError, ValueError):
            continue
        if target == base or target.startswith(base + os.sep):
            return True
    return False
