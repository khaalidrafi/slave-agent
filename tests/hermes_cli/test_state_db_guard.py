"""Tests for the state.db integrity guard (install/boot maintenance, #68474).

Exercises ``verify_sqlite_integrity`` against REAL
SQLite files (valid, zeroed, truncated) — the exact corruption signature from
issue #68474 (file kept at original size, 100% null bytes, header gone). The
pre-update backup that used to call this during ``hermes update`` was deleted
with the updater (FORK.org P0); the guard now runs from the install tail.
"""

import sqlite3

import pytest

from hermes_cli.backup import verify_sqlite_integrity


@pytest.fixture()
def valid_db(tmp_path):
    path = tmp_path / "state.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO sessions (name) VALUES (?)", [(f"s{i}",) for i in range(50)]
    )
    conn.commit()
    conn.close()
    return path










def test_oversized_db_probe_catches_malformed_schema(tmp_path):
    """Skipping the pragma must not mean skipping corruption detection.

    A file with a valid header whose schema cannot be parsed has to fail
    the oversized path via the cheap structural probe.
    """
    path = tmp_path / "state.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.commit()
    conn.close()

    raw = bytearray(path.read_bytes())
    # Corrupt the schema b-tree page (page 2 onward) while leaving the
    # 16-byte header magic intact, so only the probe can catch it.
    for i in range(100, min(len(raw), 4096)):
        raw[i] = 0xFF
    path.write_bytes(bytes(raw))

    res = verify_sqlite_integrity(path, max_bytes=1)
    assert res["valid"] is False
    assert "probe" in res["message"]






def test_restore_flow_end_to_end(valid_db, tmp_path):
    """Simulate the #68474 recovery path: live db zeroed, snapshot valid →
    restore snapshot over live file → verify restored copy."""
    import shutil

    snap = tmp_path / "state-snapshots" / "20260721-pre-update" / "state.db"
    snap.parent.mkdir(parents=True)
    shutil.copy2(valid_db, snap)

    # Zero the live db (the bug).
    size = valid_db.stat().st_size
    valid_db.write_bytes(b"\x00" * size)
    assert verify_sqlite_integrity(valid_db)["valid"] is False
    assert verify_sqlite_integrity(snap)["valid"] is True

    # The guard's restore step.
    shutil.copy2(snap, valid_db)
    restored = verify_sqlite_integrity(valid_db)
    assert restored["valid"] is True
    conn = sqlite3.connect(valid_db)
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 50
    conn.close()
