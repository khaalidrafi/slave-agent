"""LIVE Windows E2E for the gateway control socket named-pipe transport.

Runs ONLY on a real Windows host (the on-demand ``windows-venv-e2e.yml``
lane). Spawns a REAL child process that binds the REAL named pipe via the
proactor event loop with the DEFAULT verb handlers, then drives the real
sync client and the real fleet consumers against it — no mocks anywhere.

Proves, on windows-latest:
  1. `GatewayControlServer` binds ``\\\\.\\pipe\\hermes-gateway-<hash>`` via
     ``loop.start_serving_pipe`` and answers ``identify``/``status``.
  2. The sync client's pipe transport (open/write/read/busy-retry) works
     against a live server and returns the child's true pid + code identity.
  3. ``collect_fleet_versions()`` prefers the socket (``source: socket``).
  4. After the server process is force-killed, the client returns None
     (FileNotFoundError on the pipe — no stale-file hazard on Windows) and
     consumers fall back to the state-file layer, which classifies only a
     live-verified gateway PID (#110420).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.live_process_fixtures import sleeper_script_path

pytestmark = pytest.mark.platforms("windows")  # live Windows named-pipe E2E

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _wait_until(predicate, timeout: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _readline(stream, timeout: float = 60.0) -> str:
    """``stream.readline()`` bounded by *timeout* (a hung child fails, not hangs)."""
    got: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: got.put(stream.readline()), daemon=True).start()
    try:
        return got.get(timeout=timeout)
    except queue.Empty:
        return ""


def _argv_visible(pid: int, marker: str) -> bool:
    """True once the process table shows *pid* with *marker* in its argv."""
    import psutil

    try:
        return marker in " ".join(psutil.Process(pid).cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

_CHILD_CODE = r"""
import asyncio, os, sys
sys.path.insert(0, sys.argv[1])
os.environ["HERMES_HOME"] = sys.argv[2]
from gateway.control_socket import GatewayControlServer

async def main():
    server = GatewayControlServer()
    ok = await server.start()
    # Print our REAL pid: on Windows uv venvs, python.exe is a trampoline
    # that spawns the actual interpreter as a child, so Popen.pid is the
    # shim, not the server process. (That spawner-view-vs-reality gap is
    # the exact bug class the control socket exists to eliminate.)
    print(f"SERVER_STARTED {os.getpid()}" if ok else "SERVER_FAILED", flush=True)
    if not ok:
        return
    await asyncio.sleep(120)

asyncio.run(main())
"""


@pytest.fixture()
def live_server(tmp_path: Path):
    home = tmp_path / ".hermes"
    home.mkdir()
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_CODE, str(PROJECT_ROOT), str(home)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    line = _readline(proc.stdout).strip()
    if not line.startswith("SERVER_STARTED"):
        err = proc.stderr.read() if proc.poll() is not None else ""
        _kill_tree(proc)
        pytest.fail(f"pipe server child failed to start: {line!r} {err}")
    server_pid = int(line.split()[1])
    yield proc, home, server_pid
    _kill_tree(proc)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the spawned child AND its descendants (uv trampoline shims)."""
    if proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        proc.wait()


