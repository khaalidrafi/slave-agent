"""Every logger the SQLite backend writes to carries a name main's own modules log under for the same code, so the
per-component log views (``slave logs --component``, gateway.log), which select records by logger name, show the
backend's records where they show main's.

Each backend module holds the loggers it writes to as module globals; the case imports every module of the package
and reads the loggers it holds.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

import persistence.sqlite

# The names main logs under in the modules this backend's code comes from.
_MAIN_LOGGER_NAMES = frozenset({
    "gateway.hosted_room_work_records",
    "gateway.hosted_rooms_legacy_import",
    "gateway.lifecycle_ledger",
    "gateway.session",
    "gateway.session_api",
    "slave_cli.backup_restore",
    "slave_cli.backup_sqlite",
    "slave_cli.session_lost_and_found",
    "slave_cli.timefmt",
    "slave_state",
    "slave_state_health",
    "slave_state_holders",
    "slave_state_lockowners",
    "slave_state_reconcile",
    "slave_state_registry",
    "tools.async_delegation",
})


def _backend_loggers():
    """``(module, global, logger name)`` for every logger a module of ``persistence.sqlite`` holds."""
    for info in pkgutil.walk_packages(persistence.sqlite.__path__, "persistence.sqlite."):
        module = importlib.import_module(info.name)
        for attr, value in vars(module).items():
            if isinstance(value, logging.Logger):
                yield info.name, attr, value.name


def test_every_backend_logger_carries_a_name_main_logs_under():
    found = sorted(_backend_loggers())
    assert found, "no logger found under persistence.sqlite"
    strays = [f"{module}.{attr}: {name}" for module, attr, name in found if name not in _MAIN_LOGGER_NAMES]
    assert not strays, "backend loggers named outside main's names:\n" + "\n".join(strays)
