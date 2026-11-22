"""Compatibility module for outside plugins that still import ``slave_state_registry``; removed in v0.27.0.

``acquire`` opens a ``slave_state.SessionDB`` on the storage interface and ``release`` closes it; nothing is shared
between callers. The first ``acquire`` in a process emits the ``slave_state`` stand-in's one deprecation warning,
unless another stand-in name has already emitted it. A process that loaded an older release's ``slave_state`` before
an update (a long-running server importing this module lazily) gets that release's ``SessionDB``, without the warning.
"""

import warnings as _warnings

import slave_state as _slave_state


def acquire(db_path=None):
    """A ``slave_state.SessionDB`` on the store of ``db_path`` (a ``state.db``), or of the current profile."""
    first_warning = getattr(_slave_state, "_first_warning", None)
    if first_warning is None:
        return _slave_state.SessionDB(db_path)
    if first_warning():
        _warnings.warn(
            f"slave_state_registry.acquire is deprecated and is removed in {_slave_state._REMOVAL_RELEASE}; use "
            f"persistence_assembly.open_persistence(profile_scope()) instead ({_slave_state._MIGRATION_GUIDE}).",
            DeprecationWarning, stacklevel=2)
    return _slave_state._SessionDB(db_path)


def release(db) -> bool:
    """Close ``db``: ``True``, as for any ``SessionDB`` ``acquire`` lent, and ``False`` for None."""
    if db is None:
        return False
    db.close()
    return True


def release_or_close(db) -> None:
    """Close ``db``."""
    release(db)
