#!/usr/bin/env bash
# Canonical test runner for slave-agent. Run this instead of calling
# `pytest` directly to guarantee your local run matches CI behavior.
#
# What this script enforces:
#   * Per-file isolation via scripts/run_tests_parallel.py — each test
#     file runs in its own freshly-spawned `python -m pytest <file>`
#     subprocess. No xdist, no shared workers, no module-level leakage
#     between files.
#   * TZ=UTC, LANG=C.UTF-8, PYTHONHASHSEED=0 (deterministic)
#   * Env vars blanked (conftest.py also does this, but this
#     is belt-and-suspenders for anyone running pytest outside our
#     conftest path — e.g. on a single file)
#   * The checkout's test environment (via scripts/run-in-slave-env when needed)
#
# Usage:
#   scripts/run_tests.sh                            # full suite
#   scripts/run_tests.sh -j 4                       # cap parallelism
#   scripts/run_tests.sh tests/agent/               # discover only here
#   scripts/run_tests.sh tests/agent/ tests/acp_adapter/    # multiple roots
#   scripts/run_tests.sh tests/foo.py               # single file
#   scripts/run_tests.sh tests/foo.py -q            # path + bare pytest flag
#   scripts/run_tests.sh tests/foo.py -v --tb=long  # bare flags "just work"
#   scripts/run_tests.sh -k 'pattern'               # value flags pass through too
#   scripts/run_tests.sh tests/foo.py -- --tb=long  # explicit '--' still works
#
# Bare pytest flags (anything starting with '-' that isn't one of this
# runner's own options: -j/--jobs, --paths, --slice, --file-timeout, etc.)
# are forwarded to each per-file pytest invocation automatically — no '--'
# separator required. The explicit '--' form still works and stacks with
# bare flags. Positional path arguments override the default discovery
# root (tests/).

set -euo pipefail

# ── Locate repo root ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Locate python ───────────────────────────────────────────────────────────
# The suite runs under the checkout's isolated test environment (pm.testenv),
# and only there: unless the inherited environment is current for this
# checkout, this script re-executes itself under scripts/run-in-slave-env,
# which syncs and applies it. That holds however the script is launched
# (`scripts/run_tests.sh`, `bash scripts/run_tests.sh`, from CI or a shell), so
# a branch switch or lock edit never runs the suite against the previous
# dependency set.
#
# Without an activation, an explicit SLAVE_PYTHON that has pytest is honored:
# the Nix devShell's editable venv and CI's minimal installer lanes provide
# one on purpose. The import check matters: a wrapped `slave` binary exports
# SLAVE_PYTHON pointing at a release venv without pytest.
_has_pytest() { [ -n "$1" ] && [ -x "$1" ] && "$1" -c 'import pytest' 2>/dev/null; }
# shellcheck source=scripts/_activation.sh
. "$SCRIPT_DIR/_activation.sh"

# A test run under a faked HOME (worktree lanes, probe homes) provisions its
# test environment from the OS account's tool store instead of downloading
# ~1 GB of tools into every temporary home, but only while that store already
# records this checkout's pins (_store_has_pins). The check runs unlocked
# before `pm install` takes the store's install lock, so it keeps runs that
# START on different pins apart; it does not cover the window in between, where
# the account's own `slave update` (or a run on other pins) can re-point
# facts.json and this run's `pm install` then re-stages its pins over them.
# Only this runner's own provisioning gets SLAVE_RUNTIME_DIR: the pytest
# children below start from `env -i` without it, so tests that exercise setup,
# install or update resolve their own stores. Their PATH still holds the
# account store's tool dirs, so a test writing through a PATH tool
# (`pip install`, `npm -g`) would write into the account store. An explicit
# SLAVE_RUNTIME_DIR, a custom SLAVE_HOME, a home that already holds a store,
# or an account without a usable store keep today's per-home layout.
# Prints the account home, then the pinned Python minor.
_account_tool_store() {
  local account py_minor
  [ -z "${SLAVE_RUNTIME_DIR:-}" ] || return 1
  case "${SLAVE_HOME:-}" in "" | "$HOME/.slave" | "$HOME/.slave/"*) ;; *) return 1 ;; esac
  [ ! -f "$HOME/.slave/tools/facts.json" ] || return 1
  account="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)"
  [ -n "$account" ] || account="$(dscl . -read "/Users/$(id -un)" NFSHomeDirectory 2>/dev/null | sed -n 's/^NFSHomeDirectory: *//p')"
  [ -n "$account" ] && [ -d "$account" ] && [ ! "$account" -ef "$HOME" ] || return 1
  [ -f "$account/.slave/tools/facts.json" ] && [ -w "$account/.slave/tools" ] || return 1
  py_minor="$(_store_has_pins "$account/.slave/tools")" || return 1
  printf '%s\n%s\n' "$account" "$py_minor"
}
# Read-only check that the store already records this checkout's pins
# (scripts/tool_store_pins.py says why and what counts); prints the Python minor.
_store_has_pins() {
  local python
  python="$(SLAVE_RUNTIME_DIR="$1" slave_bootstrap_python "$REPO_ROOT")" || return 1
  PYTHONHOME= "$python" -I -B "$REPO_ROOT/scripts/tool_store_pins.py" "$REPO_ROOT" "$1" 2>/dev/null
}
if _shared="$(_account_tool_store)"; then
  _account="${_shared%%$'\n'*}"
  export SLAVE_RUNTIME_DIR="$_account/.slave/tools"
  # setup-slave.sh's uv-managed bootstrap interpreter is the same kind of
  # cache, but only reused: a missing pinned minor would download into it.
  if [ -z "${UV_PYTHON_INSTALL_DIR:-}" ] && [ -w "$_account/.local/share/uv/python" ] \
      && compgen -G "$_account/.local/share/uv/python/cpython-${_shared#*$'\n'}[.-]*" >/dev/null; then
    export UV_PYTHON_INSTALL_DIR="$_account/.local/share/uv/python"
  fi
  echo "▶ faked HOME: using the account's tool store $SLAVE_RUNTIME_DIR"
fi
unset _account _shared
if [ -z "${__SLAVE_ACTIVATED:-}" ] && _has_pytest "${SLAVE_PYTHON:-}"; then
  PYTHON="$SLAVE_PYTHON"
  echo "▶ not activated — using SLAVE_PYTHON: $PYTHON"
else
  if ! slave_activation_current "$REPO_ROOT"; then
    if [ -n "${__SLAVE_TESTS_REEXEC:-}" ]; then
      echo "error: run-in-slave-env did not produce a current environment for $REPO_ROOT" >&2
      exit 1
    fi
    echo "▶ environment missing or stale for $REPO_ROOT — re-running under run-in-slave-env" >&2
    export __SLAVE_TESTS_REEXEC=1
    exec "$SCRIPT_DIR/run-in-slave-env" "$BASH" "${BASH_SOURCE[0]}" "$@"
  fi
  PYTHON="${__SLAVE_TEST_PYTHON:-}"
  if ! _has_pytest "$PYTHON"; then
    echo "error: activation provided no test interpreter with pytest (__SLAVE_TEST_PYTHON=${PYTHON:-unset})" >&2
    exit 1
  fi
fi


# ── Live-gateway plugin (computed before we drop env) ───────────────────────
EXTRA_PYTHONPATH=""
EXTRA_PYTEST_PLUGINS=""
if [ -f "$HOME/.slave/pytest_live_guard.py" ]; then
  EXTRA_PYTHONPATH="$HOME/.slave"
  EXTRA_PYTEST_PLUGINS="pytest_live_guard"
fi


# ── Windows location variables (computed before we drop env) ───────────────
# `env -i` forwards HOME, which is enough on POSIX. Native Windows CPython
# resolves Path.home() from USERPROFILE (or HOMEDRIVE+HOMEPATH), stdlib
# platform paths come from LOCALAPPDATA/APPDATA, ssl/sockets need SYSTEMROOT,
# and tempfile needs TEMP/TMP. Dropping them breaks collection on native
# Windows (issues #67385, #70813). PATHEXT is also required: without .EXE,
# PowerShell opens a native child as a document without waiting for its exit.
# PSModuleAnalysisCachePath: the hosted Windows images point PowerShell at a
# shared module analysis cache, which CI warms before the tests (tests-os.yml).
# Without it a test's powershell.exe child falls back to a cold per-user cache
# and re-analyses every installed module (~22s per launch on arm64 runners).
# These are location variables, not
# credentials, so forwarding them keeps the isolation intent intact. Each is
# only forwarded when actually set, so POSIX runs are byte-for-byte unchanged.
WIN_ENV=()
for _win_var in USERPROFILE HOMEDRIVE HOMEPATH LOCALAPPDATA APPDATA SYSTEMROOT TEMP TMP \
    ComSpec PATHEXT PROGRAMFILES ProgramFiles PROGRAMDATA ProgramData PSModuleAnalysisCachePath; do
  if [ -n "${!_win_var:-}" ]; then
    WIN_ENV+=("$_win_var=${!_win_var}")
  fi
done
# Native build toolchain (Windows arm64 has no wheels for every pinned C extension, so
# `uv sync` inside a PM test compiles ruamel-yaml-clib and friends). The MSVC developer
# environment is exported by scripts/build/windows-deps.ps1 into the job env; without
# INCLUDE/LIB/VSINSTALLDIR the build backend reports "Visual C++ 14.0 or greater is
# required". These describe compiler locations, not credentials.
for _tool_var in INCLUDE LIB LIBPATH VSINSTALLDIR VCINSTALLDIR VCToolsInstallDir VCToolsVersion \
    VCToolsRedistDir WindowsSdkDir WindowsSDKVersion WindowsSdkBinPath WindowsSdkVerBinPath \
    WindowsLibPath UCRTVersion UniversalCRTSdkDir VSCMD_ARG_HOST_ARCH VSCMD_ARG_TGT_ARCH VSCMD_VER \
    DevEnvDir ExtensionSdkDir Platform CARGO_HOME RUSTUP_HOME RUSTUP_TOOLCHAIN \
    CARGO_TARGET_AARCH64_PC_WINDOWS_MSVC_LINKER CC_aarch64_pc_windows_msvc CC CXX AR \
    VCPKG_ROOT OPENSSL_DIR OPENSSL_STATIC OPENSSL_LIB_DIR OPENSSL_INCLUDE_DIR; do
  if [ -n "${!_tool_var:-}" ]; then
    WIN_ENV+=("$_tool_var=${!_tool_var}")
  fi
done
# setuptools locates the compiler through vswhere under "%ProgramFiles(x86)%\Microsoft Visual
# Studio\Installer"; without that variable a primed INCLUDE/LIB still reads as "Visual C++ 14.0
# or greater is required". The parenthesised name cannot be read with ${!var}.
_pf86="$(env | sed -n 's/^ProgramFiles(x86)=//p' | head -n1)"
[ -z "$_pf86" ] || WIN_ENV+=("ProgramFiles(x86)=$_pf86")

# ── Test-runner knobs (computed before we drop env) ────────────────────────
# The runner's own documented environment knobs must survive the hermetic
# `env -i` below, or they are silent no-ops for anyone invoking this script:
#
#   * SLAVE_TEST_WORKERS / PATHS / FILE_TIMEOUT / FILE_RETRIES / SLICE are
#     read by run_tests_parallel.py at argparse-default time — inside the
#     stripped environment.
#   * SLAVE_TEST_IMAGE is read by tests/docker/conftest.py to skip its
#     session-scoped `docker build`. CI's docker.yml sets it to the image
#     the build step just loaded; stripping it made every per-file pytest
#     subprocess rebuild the 5GB image from a cold builder cache instead
#     (~4 min per worker per run, and the rebuilt image lacked the
#     SLAVE_GIT_SHA build-arg the workflow bakes in).
#   * SLAVE_E2E_REQUIRE_TUI turns a missing Ink TUI build into a failure in
#     tests/e2e/core/terminal instead of a skip (set by the e2e CI job).
#   * CI / GITHUB_ACTIONS tell suites they run on a disposable runner (e.g.
#     tests/e2e/core/upgrade runs the real updater unsandboxed only there).
#   * SLAVE_E2E_WINDOWS_INSTALL opts tests/e2e/core/windows_update into running
#     the real install.ps1 (it writes HKCU PATH); SLAVE_E2E_MACHINE_ROOT,
#     SLAVE_E2E_PROFILES_ROOT and SLAVE_E2E_ARTIFACTS place its fake machines,
#     their user profiles and the transcripts CI uploads.
#   * SLAVE_E2E_STRICT_ACCEPTANCE makes tests/e2e/core/_pending_fixes.py's
#     known gaps hard failures in an acceptance run (workflow dispatch input).
#   * SLAVE_E2E_UPGRADE_BASE (older name SLAVE_E2E_N1_REF) picks the release
#     tests/e2e/core/upgrade starts from: a tag, a commit, or an updater
#     generation (by-path, handoff, pre-handoff); unset, the newest release.
#     SLAVE_E2E_INSTALL_REF installs a patched commit in its place (proving a
#     leg red), SLAVE_E2E_GIT_OBJECTS names an extra object store for its
#     smart-HTTP origin, SLAVE_E2E_KEEP_ROOT keeps its sandbox roots.
#   * SLAVE_TEST_SSH_HOST / _USER / _PORT / _KEY and SLAVE_TEST_DOCKER_IMAGE
#     arm the real-backend tests (tests/tools/test_ssh_environment.py,
#     tests/tools/test_docker_backend_real.py); remote-backends.yml points them at
#     a throwaway sshd container and a small public image. The key is a
#     per-run throwaway, never a credential.
#
# These are test-infrastructure knobs, not credentials — same class as the
# SLAVE_RUN_SLOW_PET_TESTS / SLAVE_E2E_BROWSER / SLAVE_RUN_E2E opt-ins
# forwarded below.
# SSL_CERT_FILE/DIR are trust-store locations: the pinned interpreter's
# OpenSSL has no compiled-in bundle path on NixOS, so network tests (PM
# downloads, channel reads) need the host's pointer to verify TLS.
# Keep this an explicit allowlist (no SLAVE_TEST_* glob) so the "no
# credential can leak" property stays auditable at a glance.
TEST_ENV=()
for _test_var in SLAVE_TEST_IMAGE SLAVE_TEST_WORKERS SLAVE_TEST_PATHS \
  SLAVE_TEST_FILE_TIMEOUT SLAVE_TEST_FILE_RETRIES SLAVE_TEST_SLICE SLAVE_TEST_FORKSERVER \
  SSL_CERT_FILE SSL_CERT_DIR SLAVE_GATEWAY_LOCK_DIR SLAVE_E2E_REQUIRE_TUI CI GITHUB_ACTIONS \
  SLAVE_E2E_WINDOWS_INSTALL SLAVE_E2E_MACHINE_ROOT SLAVE_E2E_PROFILES_ROOT SLAVE_E2E_ARTIFACTS \
  SLAVE_E2E_STRICT_ACCEPTANCE SLAVE_E2E_UPGRADE_BASE SLAVE_E2E_N1_REF \
  SLAVE_E2E_INSTALL_REF SLAVE_E2E_GIT_OBJECTS SLAVE_E2E_KEEP_ROOT \
  SLAVE_TEST_SSH_HOST SLAVE_TEST_SSH_USER SLAVE_TEST_SSH_PORT \
  SLAVE_TEST_SSH_KEY SLAVE_TEST_DOCKER_IMAGE; do
  if [ -n "${!_test_var:-}" ]; then
    TEST_ENV+=("$_test_var=${!_test_var}")
  fi
done

# ── Run in hermetic env ──────────────────────────────────────────────────────
# env -i: start with empty environment, opt-in only what we need.
# No credential var can leak — you'd have to explicitly add it here.
# Never forward SLAVE_RUNTIME_DIR or UV_PYTHON_INSTALL_DIR: under a faked HOME
# they point at the account's shared stores (see _account_tool_store).
echo "▶ running per-file parallel test suite via run_tests_parallel.py"
echo "  (TZ=UTC LANG=C.UTF-8 PYTHONHASHSEED=0; clean env)"

cd "$REPO_ROOT"

# ── Pre-compile .pyc bytecode cache ─────────────────────────────────────────
# Each test file runs in its own subprocess via run_tests_parallel.py.
# Pre-building the bytecode cache once here (instead of each subprocess
# compiling on first import) avoids redundant work across ~2000 processes.
# Uses git to list tracked .py files (skips venv, node_modules, etc).
echo "▶ pre-compiling bytecode cache"
"$PYTHON" -m compileall -q -j 0 -- $(git ls-files '*.py') >/dev/null 2>&1 || true

echo "▶ launching test runner"
exec env -i \
  PATH="$PATH" \
  HOME="$HOME" \
  ${WIN_ENV[@]+"${WIN_ENV[@]}"} \
  ${TEST_ENV[@]+"${TEST_ENV[@]}"} \
  TZ=UTC \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  PYTHONHASHSEED=0 \
  PYTHONUTF8=1 \
  ${SLAVE_RUN_SLOW_PET_TESTS:+SLAVE_RUN_SLOW_PET_TESTS="$SLAVE_RUN_SLOW_PET_TESTS"} \
  ${SLAVE_E2E_BROWSER:+SLAVE_E2E_BROWSER="$SLAVE_E2E_BROWSER"} \
  ${SLAVE_RUN_E2E:+SLAVE_RUN_E2E="$SLAVE_RUN_E2E"} \
  ${EXTRA_PYTHONPATH:+PYTHONPATH="$EXTRA_PYTHONPATH"} \
  ${EXTRA_PYTEST_PLUGINS:+PYTEST_PLUGINS="$EXTRA_PYTEST_PLUGINS"} \
  "$PYTHON" "$SCRIPT_DIR/run_tests_parallel.py" "$@"
