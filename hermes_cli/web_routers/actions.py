"""Gateway restart/drain, Hermes update refusal and background-action status dashboard routes.

Extracted from ``hermes_cli.web_server``; helpers/state that tests monkeypatch on
``web_server`` stay there and are late-bound (cycle-safe).
"""

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from hermes_cli.config import recommended_update_command_for_method
from hermes_cli.steward import is_commit_build, update_guidance
from hermes_cli.version_info import get_version_info
from hermes_cli.web_deps import LateState, late
from hermes_cli.web_server_gateway import _ACTION_LOG_FILES
from hermes_cli.web_routers._common import http_failure

_log = logging.getLogger("hermes_cli.web_server")
router = APIRouter()
status_router = APIRouter()

# Late-bound so a test's monkeypatch on the owning module wins at call time.
_spawn_gateway_restart = late("_spawn_gateway_restart")
detect_install_method = late("detect_install_method", "hermes_cli.config")
_ACTION_COMMANDS = LateState("_ACTION_COMMANDS", "hermes_cli.web_server_gateway")
_ACTION_IDS = LateState("_ACTION_IDS", "hermes_cli.web_server_gateway")
_ACTION_PROCS = LateState("_ACTION_PROCS", "hermes_cli.web_server_gateway")
_ACTION_RESULTS = LateState("_ACTION_RESULTS", "hermes_cli.web_server_gateway")


def _server_path(name: str) -> Path:
    """Live Path value (``_ACTION_LOG_DIR`` on web_server_gateway, ``PROJECT_ROOT`` on
    web_server; plain values are not proxied by LateState)."""
    import hermes_cli.web_server as ws
    import hermes_cli.web_server_gateway as gw
    return getattr(gw if name == "_ACTION_LOG_DIR" else ws, name)


_ACTION_LOG_TAIL_MAX_BYTES = 256 * 1024
_ACTION_LOG_TAIL_INITIAL_CHUNK_BYTES = 8 * 1024
_ACTION_LOG_TAIL_MAX_CHUNK_BYTES = 64 * 1024


def _finish_action(name: str, exit_code: Optional[int], pid: Optional[int]) -> None:
    """Record a terminal result and drop the live-process registries for ``name``."""
    _ACTION_RESULTS[name] = {"exit_code": exit_code, "pid": pid}
    for registry in (_ACTION_PROCS, _ACTION_COMMANDS, _ACTION_IDS):
        registry.pop(name, None)


def _record_completed_action(name: str, message: str, exit_code: int = 1) -> None:
    """Record a non-spawned action result and write it to the action log."""
    log_dir = _server_path("_ACTION_LOG_DIR")
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / _ACTION_LOG_FILES[name], "ab", buffering=0) as log_file:
        log_file.write(f"\n=== {name} completed {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
        log_file.write(message.encode("utf-8", errors="replace"))
        if not message.endswith("\n"):
            log_file.write(b"\n")
    _finish_action(name, exit_code, None)


def _tail_lines(path: Path, n: int) -> List[str]:
    """Return the last ``n`` lines of ``path`` without loading huge logs."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if n <= 0 or size <= 0:
        return []

    min_offset = max(0, size - _ACTION_LOG_TAIL_MAX_BYTES)
    offset = size
    chunk_size = _ACTION_LOG_TAIL_INITIAL_CHUNK_BYTES
    newline_count = 0
    chunks: List[bytes] = []
    drop_partial_first_line = False
    try:
        with path.open("rb") as handle:
            while offset > min_offset and newline_count <= n:
                read_size = min(chunk_size, offset - min_offset)
                offset -= read_size
                handle.seek(offset)
                chunk = handle.read(read_size)
                chunks.append(chunk)
                newline_count += chunk.count(b"\n")
                chunk_size = min(chunk_size * 2, _ACTION_LOG_TAIL_MAX_CHUNK_BYTES)
            if offset > 0:
                handle.seek(offset - 1)
                drop_partial_first_line = handle.read(1) != b"\n"
    except OSError:
        return []

    lines = b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()
    if drop_partial_first_line and lines:
        lines = lines[1:]
    return lines[-n:]


@router.post("/api/gateway/restart")
async def restart_gateway(profile: Optional[str] = None):
    """Kick off a ``hermes gateway restart`` in the background."""
    with http_failure("Failed to spawn gateway restart", 500, "Failed to restart gateway"):
        proc, _reused = _spawn_gateway_restart(profile)
    return {"ok": True, "pid": proc.pid, "name": "gateway-restart"}


@router.get("/api/gateway/migrate/plan")
async def gateway_migrate_plan():
    """Preflight for folding per-profile gateways into one multiplexer (same JSON as the CLI plan)."""
    from hermes_cli.gateway_migrate import build_migration_plan
    plan = await asyncio.to_thread(build_migration_plan)
    return plan.to_dict()


@router.post("/api/gateway/migrate")
async def gateway_migrate():
    """Run ``hermes gateway migrate --multiplex --yes`` detached; the CLI re-runs the preflight and
    refuses (exit 1 into the action log) when blocked, so the UI should gate on the plan first."""
    from hermes_cli.web_server_gateway import _spawn_hermes_action
    with http_failure("Failed to spawn gateway migrate", 500, "Failed to start gateway migration"):
        proc = _spawn_hermes_action(["gateway", "migrate", "--multiplex", "--yes"], "gateway-migrate")
    return {"ok": True, "pid": proc.pid, "name": "gateway-migrate"}


@router.post("/api/gateway/drain")
async def gateway_drain(request: Request):
    """Begin or cancel an external (NAS-driven) gateway drain.

    Authenticated by the non-interactive token-auth seam (the ``dashboard_auth/drain``
    plugin registers this path as a token route and verifies the bearer secret);
    without that plugin the cookie gate covers a gated bind and the legacy
    session-token gate a loopback bind — never unauthenticated on a network bind.

    Body ``{"action": "drain"|"cancel"}``. Only the ``.drain_request.json`` marker is
    written/removed here — the gateway's ``_drain_control_watcher`` owns the state
    transition (the marker IS the control channel). Idempotent on both sides;
    ``POST /api/gateway/restart`` is the force-override that supersedes a drain.
    """
    from gateway.drain_control import clear_drain_request, drain_requested, write_drain_request

    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    action = str(body.get("action", "drain")).strip().lower()
    # Attribute to the verified token principal when the token-auth seam attached one.
    principal = getattr(getattr(request.state, "token_principal", None), "principal", None) or "dashboard"

    if action == "cancel":
        existed = clear_drain_request()
        _log.info("Gateway drain CANCEL requested by %s (existed=%s)", principal, existed)
        return {"ok": True, "action": "cancel", "was_draining": existed}
    if action != "drain":
        raise HTTPException(status_code=400, detail=f"Unknown drain action {action!r}; expected 'drain' or 'cancel'")

    payload = write_drain_request(
        principal=str(principal), suppress_notification=bool(body.get("suppress_notification", False)),
    )
    _log.info(
        "Gateway drain BEGIN requested by %s (suppress_notification=%s)", principal, payload["suppress_notification"],
    )
    return {
        "ok": True, "action": "drain", "requested_at": payload["requested_at"],
        # Echo so a caller polling /api/status knows the marker is now set;
        # the gateway watcher flips gateway_state -> draining within ~1s.
        "draining": drain_requested(), "suppress_notification": payload["suppress_notification"],
    }


def _update_state() -> Dict[str, Any]:
    """What this install is, and the one honest answer about updating it.

    Shared by the check (GET) and the apply (POST): a build with no updater must not
    describe itself differently depending on which button was pressed. ``behind`` is
    always None because no update source is consulted any more — the checker went with
    the updater (FORK.org P0) — so ``update_available`` and ``can_apply`` are False.
    """
    root = _server_path("PROJECT_ROOT")
    install_method = "desktop-app" if is_commit_build(root) else detect_install_method(root)
    return {
        "install_method": install_method,
        "current_version": get_version_info().derived_version,
        "behind": None,
        "update_available": False, "can_apply": False,
        "update_command": recommended_update_command_for_method(install_method),
        "message": update_guidance(root),
    }


def _update_refused(state: Dict[str, Any]) -> Dict[str, Any]:
    """The refusal, logged as a completed action so a client polling the status
    sees the tile finish (exit 1) instead of waiting on a process that never ran."""
    _record_completed_action("hermes-update", state["message"], exit_code=1)
    return {
        "ok": False, "pid": None, "name": "hermes-update", "error": "update_not_in_place",
        "message": state["message"], "update_command": state["update_command"],
    }


@router.post("/api/hermes/update")
async def update_hermes():
    """Refuse to update: this build has no in-place updater (FORK.org P0).

    The tile still answers, because Desktop and the dashboard both hold an Update button.
    It reports the same thing ``hermes update`` prints — the package manager that owns
    this install — instead of spawning a process whose whole job is to print that.
    """
    return _update_refused(_update_state())


@router.get("/api/hermes/update/check")
async def check_hermes_update():
    """Report what this install is, and that nothing here can update it.

    Returns install_method ('apt'|'git'|'docker'|'nix'|'nixos'|'unknown'),
    current_version, and the refusal the POST side gives: ``message`` names the package
    manager that owns the tree. ``force`` and ``profile`` query args are still sent by
    clients and ignored — they used to bust the 24h GitHub cache and scope the check.
    """
    return _update_state()


@status_router.get("/api/actions/{name}/status")
async def get_action_status(name: str, lines: int = 200):
    """Tail an action log and report whether the process is still running."""
    log_file_name = _ACTION_LOG_FILES.get(name)
    if log_file_name is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {name}")

    log_dir = _server_path("_ACTION_LOG_DIR")
    tail = _tail_lines(log_dir / log_file_name, min(max(lines, 1), 2000))

    proc = _ACTION_PROCS.get(name)
    if proc is None:
        # No live process: the recorded result is the whole story. An update
        # never had one here — the POST refuses without spawning (FORK.org P0).
        result = _ACTION_RESULTS.get(name)
        running = False
        pid = result.get("pid") if result else None
        exit_code = result.get("exit_code") if result else None
    else:
        exit_code = proc.poll()
        running = exit_code is None
        pid = proc.pid
        if exit_code is not None:
            with contextlib.suppress(Exception):
                proc.wait(timeout=1)
            _finish_action(name, exit_code, pid)

    return {"name": name, "running": running, "exit_code": exit_code, "pid": pid, "lines": tail}


@status_router.get("/api/hermes/update/receipt")
async def get_update_receipt():
    """Always 404: this build writes no update receipts, because it has no updater.

    The route exists so a client that still polls it gets a sentence explaining
    why there is nothing to read, rather than FastAPI's bare "Not Found".
    """
    raise HTTPException(status_code=404, detail="This build does not update in place, so it records no receipts.")

