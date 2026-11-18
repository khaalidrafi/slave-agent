"""Self-test for the live-system guard fixture in tests/conftest.py.

This file is the canary. If anyone removes a guard or weakens it, these
tests fail. If anyone adds a NEW kill primitive to the codebase without
adding it to the guard, the corresponding test added here will fail too.

The guard exists to protect the developer's live ``slave-gateway`` process
from being SIGTERMed by tests, and every live slave-agent systemd unit
(``slave-gateway*``, ``slave-dashboard*``, ``slave-serve*``) from being
restarted or stopped by them. See PR #23397 for the original incident
(5+ live gateway kills in 3 days). Per Teknium 2026-05-10:

  > "You better do such a deep scan and scrub of the tests that this
  >  never is possible ever again for all eternity."

Every primitive that can deliver a signal to a foreign process or mutate
the live systemd unit MUST be exercised below. Adding a new primitive to
the guard? Add a test here too.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import types

import pytest

# A guaranteed-foreign PID: PID 1 (init).  Owned by root, not us, and
# always exists. A sane guard refuses to signal it.
FOREIGN_PID = 1


# ──────────────────── fail-closed self-protection ──────────────
#
# This file executes REAL kill primitives — os.kill(-1, SIGTERM), os.killpg,
# pkill -f python — and depends entirely on the autouse ``_live_system_guard``
# fixture in tests/conftest.py to intercept them. That makes the canary
# fail-OPEN: in any collection context where this file is present but its home
# conftest is not, the primitives fire for real and ``os.kill(-1, SIGTERM)``
# SIGTERMs every process the invoking user owns (a full desktop-session kill was
# reported in the field — see issue #68311). Such contexts are not exotic:
# published sdists that ship ``tests/`` but not ``tests/conftest.py``, trees
# assembled by copying ``test*.py`` files (that glob does NOT match
# ``conftest.py``), ``pytest --noconftest``, or running from a foreign rootdir.
#
# The fixture below makes the canary fail-CLOSED instead: it refuses to run any
# test in this file unless the guard is provably active, so no collection
# context can ever detonate the primitives. The one thing the canary can detect
# about its own safety is that the guard monkeypatches ``os.kill`` with a plain
# Python function, whereas the unguarded primitive is a C builtin.


def _live_system_guard_is_active() -> bool:
    """True iff tests/conftest.py's ``_live_system_guard`` has patched os.kill.

    The guard replaces ``os.kill`` with a plain Python function; the raw,
    unguarded primitive is a C builtin (``types.BuiltinFunctionType``). If
    ``os.kill`` is still the builtin, the guard never loaded and every kill
    primitive in this file would fire for real.
    """
    return not isinstance(os.kill, types.BuiltinFunctionType)


@pytest.fixture(autouse=True)
def _refuse_to_fire_live_weapons(request):
    """Fail closed: refuse to run a canary test unless the guard is active.

    Tests genuinely marked ``@pytest.mark.live_system_guard_bypass`` opt out
    (they run the raw primitive deliberately and harmlessly, e.g. a signal-0
    liveness probe of our own PID), matching the guard's own bypass contract.
    """
    if request.node.get_closest_marker("live_system_guard_bypass"):
        yield
        return
    if not _live_system_guard_is_active():
        pytest.fail(
            "REFUSING TO RUN: the live-system guard from tests/conftest.py is "
            "not active in this interpreter (os.kill is still the raw C "
            "builtin). This canary file executes real kill primitives — "
            "os.kill(-1, SIGTERM), os.killpg, pkill -f python — and relies on "
            "the guard to intercept them; unguarded, they SIGTERM every process "
            "the current user owns. This usually means the file was collected "
            "without its home tests/conftest.py (note: a test*.py copy glob "
            "does NOT match conftest.py). See issue #68311.",
            pytrace=False,
        )
    yield


def test_fail_closed_probe_reports_guard_active():
    """In the real suite the guard is loaded, so the probe reports active and
    ``_refuse_to_fire_live_weapons`` stays out of the way (no false positives
    that would wedge CI)."""
    assert _live_system_guard_is_active() is True




# ──────────────────── kill primitives ─────────────────────────


@pytest.mark.platforms("linux")
def test_os_kill_blocks_foreign_pid():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.kill(FOREIGN_PID, signal.SIGTERM)


def test_os_kill_blocks_negative_one():
    """``os.kill(-1, sig)`` signals every process we can reach. Must be blocked."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.kill(-1, signal.SIGTERM)


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="killpg POSIX-only")
def test_os_killpg_blocks_foreign_pgid():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.killpg(FOREIGN_PID, signal.SIGTERM)


# ──────────────────── subprocess regex bypasses ────────────────


def test_subprocess_run_systemctl_restart_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["systemctl", "--user", "restart", "slave-gateway"], check=False)


def test_subprocess_run_full_path_systemctl_blocked():
    """``/usr/bin/systemctl`` (full path) must be blocked too."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["/usr/bin/systemctl", "--user", "stop", "slave-gateway"], check=False)


def test_subprocess_run_sudo_systemctl_blocked():
    """``sudo systemctl ...`` defeated the old head==systemctl check."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["sudo", "systemctl", "restart", "slave-gateway"], check=False)


def test_subprocess_run_env_systemctl_blocked():
    """``env systemctl ...`` similarly defeated the old head check."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["env", "systemctl", "--user", "restart", "slave-gateway"], check=False)


def test_subprocess_run_bash_c_systemctl_blocked():
    """``bash -c "systemctl ..."`` must also be caught."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["bash", "-c", "systemctl --user restart slave-gateway"], check=False)




@pytest.mark.parametrize(
    "cmd",
    [
        ["systemctl", "--user", "restart", "slave-dashboard.service"],
        ["systemctl", "--user", "restart", "slave-dashboard-work.service"],
        ["systemctl", "--user", "stop", "slave-serve"],
        ["/usr/bin/systemctl", "--user", "--no-ask-password", "restart", "slave-serve-work.service"],
        ["bash", "-c", "systemctl --user restart slave-dashboard.service"],
        "systemctl --user restart slave-dashboard-work.service",
        'bash -c "systemctl --user restart slave-serve.service"',
    ],
)
def test_subprocess_run_systemctl_mutating_any_slave_unit_blocked(cmd):
    """Not just the gateway: a test that forgot to stub the runner restarted the developer's
    real slave-dashboard / slave-serve units, which the gateway-only tokens let through."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(cmd, shell=isinstance(cmd, str), check=False)


@pytest.mark.parametrize(
    "cmd",
    [
        ["systemctl", "--user", "show", "slave-dashboard.service", "--property=MainPID"],
        ["systemctl", "--user", "status", "slave-dashboard"],
        ["systemctl", "--user", "is-active", "slave-serve.service"],
        ["systemctl", "--user", "restart", "nginx.service"],
        ["systemctl", "--user", "restart", "myhermes-dashboard.service"],
    ],
)
def test_subprocess_run_systemctl_read_only_or_foreign_unit_passes_guard(cmd):
    """Read-only verbs on slave-agent units and mutating verbs on other units reach the real
    ``subprocess.run``; an empty PATH turns that into FileNotFoundError, never a real systemctl."""
    with pytest.raises(FileNotFoundError):
        subprocess.run(cmd, env={"PATH": "/nonexistent"}, check=False)


@pytest.mark.parametrize(
    "cmd",
    [
        ["bash", "-c", r"systemctl st\op slave.service"],
        ["bash", "-c", r"systemctl --user rest\art slave-dashboard"],
        r"systemctl --user re\start slave-serve.service",
        ["bash", "-c", "sh -c 'systemctl --user restart slave-dashboard'"],
    ],
)
def test_subprocess_run_shell_escaped_or_nested_verb_blocked(cmd):
    """The shell runs ``rest\\art`` as ``restart``; the guard must read it the same way."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(cmd, shell=isinstance(cmd, str), check=False)


def test_a_test_owned_unit_can_be_cleaned_up_but_no_other(request):
    """A unit the test created under its own name may be stopped; every other slave-agent unit stays refused."""
    owned = "slave-worker-kanban-t_selftest-run-1.scope"
    request.node.live_system_guard_owned_units = {owned}
    with pytest.raises(FileNotFoundError):
        subprocess.run(["systemctl", "--user", "stop", owned], env={"PATH": "/nonexistent"}, check=False)
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["systemctl", "--user", "stop", owned, "slave-dashboard.service"], check=False)
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["systemctl", "--user", "stop", "slave-worker-kanban-other-run-1.scope"], check=False)


def test_subprocess_run_setsid_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["setsid", "systemctl", "kill", "slave-gateway"], check=False)


def test_host_gateway_start_blocked_but_container_exec_allowed():
    """A host-side ``slave gateway start`` spawns a real runtime; the same words addressed to
    a container via ``docker exec`` stay inside it and are the Docker harness's business."""
    with pytest.raises(RuntimeError, match="REAL slave gateway runtime"):
        subprocess.run(["slave", "-p", "p", "gateway", "start"], check=False)
    argv = ["docker", "exec", "-u", "slave", "slave-test-x", "sh", "-c", "slave -p p gateway start"]
    # Past the guard the call reaches the real subprocess.run; a missing binary is fine here.
    with pytest.raises(FileNotFoundError):
        subprocess.run(argv, env={"PATH": "/nonexistent"}, check=False)


def test_subprocess_run_string_shell_true_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(
            "systemctl --user restart slave-gateway",
            shell=True,
            check=False,
        )


def test_subprocess_popen_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen(["systemctl", "--user", "stop", "slave-gateway"])


def test_subprocess_call_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.call(["systemctl", "--user", "restart", "slave-gateway"])


def test_subprocess_check_call_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.check_call(["systemctl", "--user", "restart", "slave-gateway"])


def test_subprocess_check_output_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.check_output(["systemctl", "--user", "restart", "slave-gateway"])


def test_subprocess_getoutput_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.getoutput("systemctl --user restart slave-gateway")


def test_subprocess_getstatusoutput_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.getstatusoutput("systemctl --user restart slave-gateway")


# ──────────────────── os.system / os.popen ────────────────────


def test_os_system_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.system("systemctl --user restart slave-gateway")


def test_os_popen_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.popen("systemctl --user restart slave-gateway")


# ──────────────────── pty.spawn ────────────────────────────────


@pytest.mark.platforms("linux")
def test_pty_spawn_systemctl_blocked():
    import pty
    with pytest.raises(RuntimeError, match="live-system guard"):
        pty.spawn(["systemctl", "--user", "restart", "slave-gateway"])


# ──────────────────── asyncio.create_subprocess_* ──────────────


def test_asyncio_create_subprocess_exec_systemctl_blocked():
    import asyncio

    async def _attempt():
        await asyncio.create_subprocess_exec(
            "systemctl", "--user", "restart", "slave-gateway"
        )

    with pytest.raises(RuntimeError, match="live-system guard"):
        asyncio.run(_attempt())


def test_asyncio_create_subprocess_shell_systemctl_blocked():
    import asyncio

    async def _attempt():
        await asyncio.create_subprocess_shell(
            "systemctl --user restart slave-gateway"
        )

    with pytest.raises(RuntimeError, match="live-system guard"):
        asyncio.run(_attempt())


# ──────────────────── pkill / killall / taskkill ───────────────


def test_subprocess_pkill_slave_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["pkill", "-f", "slave"], check=False)




def test_subprocess_pkill_python_dash_f_blocked():
    """``pkill -f python`` matches the gateway's "python -m slave_cli.main"."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["pkill", "-f", "python"], check=False)


def test_subprocess_killall_slave_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["killall", "slave"], check=False)


# ──────────────────── pass-through cases (must NOT raise) ──────
















# ──────────────────── real gateway runtime spawn ─────────────────


def test_subprocess_popen_real_gateway_restart_blocked():
    """``python -m slave_cli.main gateway restart`` is a detached child that
    inherits the pytest-tmp SLAVE_HOME, resolves the developer's real
    ``slave-gateway`` unit, and outlives the test (39 six-day orphans squatted
    the webhook port, 2026-09-03). Blocked at the spawn primitive."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen(
            [sys.executable, "-m", "slave_cli.main", "gateway", "restart"],
            start_new_session=True,
        )


def test_subprocess_popen_inline_source_restart_watcher_blocked():
    """``gateway._spawn_gateway_restart_watcher`` hides the real gateway argv behind
    ``python -c <src> <old_pid> …``. The identity matcher must ignore that trailing argv (#107002),
    but the guard reads it as SPAWN INTENT — otherwise the watcher sails through, waits out its
    120s deadline and leaves a real detached gateway squatting the webhook port."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(1)", "4242",
             sys.executable, "-m", "slave_cli.main", "gateway", "run"],
            start_new_session=True,
        )


def test_subprocess_run_gateway_status_passes_through():
    """Only lifecycle verbs are blocked: ``gateway status`` (and every other
    read-only subcommand) must still spawn — via the canonical matcher, not an
    argv substring."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; print(sys.argv[1:])", "-m", "slave_cli.main", "gateway", "status"],
        capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0


# ──────────────────── bypass marker ─────────────────────────────


@pytest.mark.live_system_guard_bypass
def test_bypass_marker_disables_guard():
    """The bypass marker exists for tests that genuinely need real signal delivery
    (e.g. PTY tests SIGINTing their own child). Verify it works.

    We use it harmlessly here by signaling our own PID 0 (own group) so we
    don't actually kill anything — but the call goes through real os.kill.
    """
    # With bypass, the guard yields without installing the monkeypatch,
    # so we get the real os.kill. Calling os.kill(os.getpid(), 0) just
    # checks that the PID exists — harmless.
    os.kill(os.getpid(), 0)  # No exception — guard is OFF.
    # Signal 0 passes the guard too, so prove the patch itself is absent.
    assert not _live_system_guard_is_active()
