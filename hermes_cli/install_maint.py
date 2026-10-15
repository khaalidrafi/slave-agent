"""Post-build maintenance for source installs and finished update tails.

Re-homed here (FORK.org P0) when the self-update subsystem was deleted: the
installers and ``hermes_cli/source_completion.py`` share this one tail, so an
install and a completed source update cannot drift apart. What the old
``update_cmd_maint``/``update_cmd_config`` chain did around ``hermes update``
-- state.db integrity guard, release-history refresh, catalog seeds, skills
sync, per-profile syncs, config migration, notices -- lives here, minus the
updater-only parts (pre-update snapshots and their safety nets, the desktop
TCC notice, gateway-mode prompts, the Windows PATH self-migration).

Names keep their historical spelling so upstream fixes to these steps stay
mergeable. Two entries, for two callers: ``run_post_install_maintenance`` is the
print-bearing tail an installer or a completed source build runs, and
``BOOT_HOME_STEPS`` + ``run_steps`` are the quiet per-revision repairs
``hermes_cli.boot_bootstrap`` gates on its install record.
"""

import logging
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger("hermes_cli.install_maint")

# One reusable set of text-mode subprocess kwargs: every git child below runs
# from tails that can be console-less on Windows and must never pop one.
from hermes_cli._subprocess_compat import windows_hide_flags  # noqa: E402  (rooted at PROJECT_ROOT first)

_GIT_TEXT_KW = dict(capture_output=True, text=True, encoding="utf-8", errors="replace",
                    creationflags=windows_hide_flags())


@contextmanager
def _best_effort(message: str):
    """Run a non-critical maintenance step; swallow ``Exception`` and log at debug."""
    try:
        yield
    except Exception as exc:
        logger.debug(message, exc)


def _load_updates_cfg() -> dict:
    """``updates`` section of config.yaml; ``{}`` on any failure."""
    from hermes_cli.config import load_config
    cfg = load_config() or {}
    updates = cfg.get("updates", {}) if isinstance(cfg, dict) else {}
    return updates if isinstance(updates, dict) else {}


def _no_prompt_git_kwargs() -> dict:
    """``subprocess.run`` kwargs for network git calls.

    GitHub answers anonymous fetches with HTTP 401 during outages; git then
    prompts ``Username for 'https://github.com':`` on the inherited terminal
    and the tail waits forever. Disable the prompt so the fetch fails fast.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    return {"stdin": subprocess.DEVNULL, "env": env, "creationflags": windows_hide_flags()}


def _branch_head_label(git_cmd=None, cwd=None) -> str | None:
    """``"<branch> @ <short-sha>"`` for the checkout (``detached`` when not on a branch), or None."""
    try:
        cmd = list(git_cmd) if git_cmd else ["git"]
        root = cwd if cwd is not None else PROJECT_ROOT

        def _rev_parse(*args):
            return subprocess.run(cmd + ["rev-parse", *args], cwd=root, **_GIT_TEXT_KW)

        branch, sha = _rev_parse("--abbrev-ref", "HEAD"), _rev_parse("--short", "HEAD")
        branch_name, sha_text = branch.stdout.strip(), sha.stdout.strip()
        if branch.returncode != 0 or sha.returncode != 0 or not sha_text or not branch_name:
            return None
        return f"{'detached' if branch_name == 'HEAD' else branch_name} @ {sha_text}"
    except Exception:
        return None


def _branch_head_suffix(git_cmd=None, cwd=None) -> str:
    """`` [<branch> @ <sha>]`` suffix for summary lines ("" when unknown)."""
    label = _branch_head_label(git_cmd, cwd)
    return f" [{label}]" if label else ""


# Reinstalling through the official installer swaps in a Python whose SQLite is safe; the
# one-liner differs per OS (mirrors ``uninstall._REINSTALL_HINT``).
_REINSTALL_ONE_LINER = {
    True: "iex (irm https://hermes-agent.nousresearch.com/install.ps1)",
    False: "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
}


def _sqlite_partial_completion_lines(sqlite_version: str) -> list[str]:
    """Completion wording for a vulnerable post-build SQLite: the lead names the
    consequence, the second line the exact fix command."""
    return [
        f"⚠ Update partially complete — your Python's SQLite ({sqlite_version}) has a known "
        "corruption bug. Hermes works, but sessions could be damaged.",
        f"  Fix: run the installer again ({_REINSTALL_ONE_LINER[sys.platform == 'win32']}) "
        "which installs a safe Python, then run `hermes doctor` to confirm.",
    ]


def _print_update_completion(message: str) -> None:
    """Print the outcome with branch @ sha so a stale checkout is visible."""
    print(f"{message}{_branch_head_suffix()}")


def _checkout_version() -> str | None:
    """The checkout's runtime identity, computed exactly as ``write_source_stamp`` publishes it.

    pyproject.toml is an inert 0.0.0 on source checkouts; the release a checkout
    runs is derived from its reachable tags.
    """
    from hermes_cli.version_info import _git_version_info
    info = _git_version_info(PROJECT_ROOT, include_untracked=True)
    return info.derived_version if info.commit else None


def _update_complete_message(pre_version: str | None) -> str:
    """Completion line with ``vA → vB`` when known; plain when either side is unknown or
    the version did not change."""
    def shown(version: str) -> str:
        # A tagless checkout's identity is ``git.<sha>``, not a release number.
        return f"v{version}" if version[:1].isdigit() else version

    post_version = _checkout_version()
    if pre_version and post_version and pre_version != post_version:
        return f"✓ Update complete! ({shown(pre_version)} → {shown(post_version)})"
    if post_version:
        return f"✓ Update complete! ({shown(post_version)})"
    return "✓ Update complete!"


def _post_update_sqlite_runtime_status():
    """Return whether the interpreter used after the tail has safe SQLite."""
    from hermes_cli.sqlite_runtime import probe_sqlite_runtime
    # Completion runs on PM's selected Python, not any obsolete repo venv.
    info = probe_sqlite_runtime(Path(sys.executable))
    return info is not None and not info.wal_reset_vulnerable, info


def _print_verified_update_completion(message: str) -> bool:
    """Print a success completion only after probing the next Hermes runtime."""
    if not message.startswith("✓"):
        _print_update_completion(message)
        return False
    sqlite_runtime_ok, sqlite_info = _post_update_sqlite_runtime_status()
    if sqlite_info is None:
        # Grace path: an unprobeable interpreter must not fail the install —
        # only a POSITIVE vulnerable probe withholds success.
        logger.debug("Post-build SQLite runtime probe unavailable; not blocking")
    if sqlite_info is None or sqlite_runtime_ok:
        _print_update_completion(message)
        return True
    print()
    for line in _sqlite_partial_completion_lines(sqlite_info.sqlite_version_string):
        print(line)
    return False


def _clear_stale_sqlite_sidecars(db_path: Path) -> None:
    """Delete -wal/-shm/-journal next to *db_path*, immediately before overwriting it with a
    snapshot image (a leftover WAL would replay over the fresh image)."""
    for suffix in ("-wal", "-shm", "-journal"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def _restore_state_db_from_snapshot(state_path: Path, snap_state: Path) -> bool:
    """Replace *state_path* with the snapshot image; True when the result passes integrity.

    Refuses (False) while another process — or a live connection in THIS process —
    holds the DB: copying over a live writer's inode desyncs its page cache.
    Raises OSError if the copy fails.
    """
    from hermes_cli.backup import verify_sqlite_integrity
    from hermes_cli.backup_restore import _foreign_db_holder_pids
    from hermes_cli.sqlite_safe_read import LiveConnectionError, offline_file_access
    holders = _foreign_db_holder_pids(state_path)
    if holders:
        print(
            f"  ✗ Auto-restore refused: process(es) {holders} still hold "
            "state.db or its WAL open. Stop them (hermes gateway stop), "
            "then restore manually with /snapshot restore."
        )
        return False
    try:
        with offline_file_access(state_path, what="restore a snapshot over"):
            _clear_stale_sqlite_sidecars(state_path)
            shutil.copy2(snap_state, state_path)
    except LiveConnectionError as exc:
        print(
            f"  ✗ Auto-restore refused: {exc} Close the in-process database "
            "handles (or restart Hermes) and retry."
        )
        return False
    restored = verify_sqlite_integrity(state_path, check_header=True, run_pragma=True)
    return bool(restored.get("valid"))


def _verify_and_restore_one_state_db(home: Path, *, label: str) -> None:
    """Integrity check + auto-restore for ONE home's state.db from its newest valid snapshot.
    Never raises: a guard that crashes the tail is worse than what it detects."""
    try:
        from hermes_cli.backup import _quick_snapshot_root, verify_sqlite_integrity
        state_path = home / "state.db"
        if not state_path.exists():
            return
        ok = verify_sqlite_integrity(state_path, check_header=True, run_pragma=True)
        if ok.get("valid"):
            logger.debug("state.db integrity OK (%s): %s", label, ok.get("message"))
            return
        print()
        print(f"⚠ state.db is corrupted after the build ({label}): " + ok.get("message", "unknown error"))
        snap_root = _quick_snapshot_root(home)
        if not snap_root.exists():
            print("  ⚠ No snapshot for this home")
            return
        for snap_dir in sorted((d for d in snap_root.iterdir() if d.is_dir()), reverse=True):
            snap_state = snap_dir / "state.db"
            if not snap_state.exists():
                continue
            if not verify_sqlite_integrity(snap_state, check_header=True, run_pragma=True).get("valid"):
                continue
            try:
                if _restore_state_db_from_snapshot(state_path, snap_state):
                    print(f"  ✓ Auto-restored from snapshot {snap_dir.name} ({label})")
                else:
                    print("  ✗ Auto-restore FAILED — restored copy also failed integrity")
            except OSError as exc:
                print("  ✗ Auto-restore file copy failed: %s" % exc)
            return
        print("  ⚠ No valid snapshot found for this home")
    except Exception as exc:
        logger.debug("state.db guard (%s) failed: %s", label, exc)


def _verify_and_restore_state_dbs_post_update() -> None:
    """Integrity guard for the ROOT state.db AND every sibling profile's. See #97994."""
    from hermes_cli.config import get_hermes_home
    home = get_hermes_home()
    _verify_and_restore_one_state_db(home, label="default home")
    with _best_effort('Sibling-profile state.db guard sweep failed: %s'):
        from hermes_cli.backup import _sibling_profile_homes
        for name, profile_home in _sibling_profile_homes(home):
            _verify_and_restore_one_state_db(profile_home, label=f"profile {name}")


def _invalidate_live_plugin_catalog_caches() -> None:
    """Drop the cached live plugin catalog under the active home AND every sibling profile's:
    the checkout is shared, so a pre-build snapshot must not out-vote the pins/entries this
    build just installed for the rest of the cache TTL (#119340)."""
    from hermes_cli.config import get_hermes_home
    home = get_hermes_home()
    from hermes_cli.plugin_catalog import invalidate_live_cache_for_home
    invalidate_live_cache_for_home(home)
    with suppress(Exception):
        from hermes_cli.backup import _sibling_profile_homes
        for _name, profile_home in _sibling_profile_homes(home):
            invalidate_live_cache_for_home(profile_home)


def _print_bundled_skills_sync_report() -> None:
    """Run ``sync_skills`` (copies new, updates changed, respects user deletions) and print its summary."""
    from tools.skills_sync import sync_skills
    result = sync_skills(quiet=True)
    if result["copied"]:
        print(f"  + {len(result['copied'])} new: {', '.join(result['copied'])}")
    if result.get("updated"):
        print(f"  ↑ {len(result['updated'])} updated: {', '.join(result['updated'])}")
    if result.get("user_modified"):
        print(f"  ~ {len(result['user_modified'])} user-modified (kept)")
        print("    → see them: hermes skills list-modified  (diff/reset to resume updates)")
    if result.get("cleaned"):
        print(f"  − {len(result['cleaned'])} removed from manifest")
    if result.get("relocated"):
        print(f"  → {len(result['relocated'])} moved to new upstream paths: {', '.join(result['relocated'])}")
    if not result["copied"] and not result.get("updated"):
        print("  ✓ Skills are up to date")


def _profile_skill_sync_status(r) -> str:
    if r and r.get("skipped_opt_out"):
        return "opted out (--no-skills)"
    if not r:
        return "sync failed"
    parts = []
    for key, fmt in (("copied", "+{} new"), ("updated", "↑{} updated"), ("user_modified", "~{} user-modified")):
        count = len(r.get(key, []))
        if count:
            parts.append(fmt.format(count))
    return ", ".join(parts) if parts else "up to date"


def _sync_profiles_after_update() -> None:
    """Best-effort per-profile syncs: bundled skills, ``.env`` backfill, Honcho profiles."""
    with suppress(Exception):
        from hermes_cli.profiles import list_profiles, seed_profile_skills
        all_profiles = list_profiles()
        if all_profiles:
            print()
            print("→ Syncing bundled skills to all profiles...")
            for p in all_profiles:
                try:
                    print(f"  {p.name}: {_profile_skill_sync_status(seed_profile_skills(p.path, quiet=True))}")
                except Exception as pe:
                    print(f"  {p.name}: error ({pe})")

    # Backfill .env for profiles created before .env seeding (copy the default's) so they
    # keep the credentials they were effectively using. See #44792.
    with suppress(Exception):
        from hermes_cli.profiles import backfill_profile_envs
        backfilled = backfill_profile_envs(quiet=True)
        if backfilled:
            print()
            print(f"→ Seeded .env for {len(backfilled)} profile(s) (copied from default): {', '.join(backfilled)}")

    with suppress(Exception):
        from plugins.memory import import_provider_module
        synced = import_provider_module("honcho", "cli").sync_honcho_profiles_quiet()
        if synced:
            print(f"\n-> Honcho: synced {synced} profile(s)")


def _format_time_ago(iso_ts: str) -> str:
    """Render an ISO timestamp as `Xh ago` / `Xd ago` / `Xm ago`. Best effort."""
    try:
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - ts).total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return "recently"


def _print_curator_first_run_notice() -> None:
    """Curator heads-up after a build. Fires only when enabled AND never run."""
    try:
        from agent import curator
        if not curator.is_enabled():
            return
        state = curator.load_state()
    except Exception:
        return
    if state.get("last_run_at"):
        return
    try:
        hours = curator.get_interval_hours()
    except Exception:
        hours = 24 * 7
    days = max(1, hours // 24)
    print()
    print("ℹ Skill curator")
    print(
        f"  Background skill maintenance is enabled. First pass is deferred "
        f"~{days}d after installation; only agent-created skills are in "
        f"scope and nothing is ever auto-deleted (archive is recoverable)."
    )
    print("  Preview now:  hermes curator run --dry-run")
    print("  Pause it:     hermes curator pause")


def _print_curator_recent_run_notice() -> None:
    """Print the latest background curator run summary once, stamping
    ``last_run_summary_shown_at``. Silent when never run, shown, or no renames."""
    try:
        from agent import curator
        state = curator.load_state()
    except Exception:
        return

    last_run_at = state.get("last_run_at")
    if not last_run_at:
        return
    if state.get("last_run_summary_shown_at") == last_run_at:
        return
    summary = state.get("last_run_summary") or ""
    if not summary:
        return

    if "\n" in summary:
        print()
        print(f"ℹ Skill curator — last run {_format_time_ago(last_run_at)}")
        for line in summary.splitlines():
            print(f"  {line}")
        print("  (This message shows once per curator run. View anytime: hermes curator status)")

    with suppress(Exception):
        state["last_run_summary_shown_at"] = last_run_at
        curator.save_state(state)


def _print_fts_optimize_available_notice() -> None:
    """Advertise the opt-in FTS storage rebuild when state.db still needs one.

    ``sessions.fts_optimize_notice``: ``advise`` (default), ``require``, ``off``.
    """
    try:
        from hermes_cli.config import load_config
        mode = str(((load_config() or {}).get("sessions") or {}).get("fts_optimize_notice", "advise")).strip().lower()
    except Exception:
        mode = "advise"
    if mode == "off":
        return

    try:
        from hermes_constants import get_hermes_home
        from hermes_state import SessionDB
    except Exception:
        return
    db_path = get_hermes_home() / "state.db"
    if not db_path.exists():
        return
    try:
        size_gb = db_path.stat().st_size / (1024 ** 3)
    except OSError:
        return
    if size_gb < 0.5:
        return  # Small DBs: the win isn't worth the nag.
    db = None
    needs_upgrade = False
    try:
        db = SessionDB(db_path=db_path, read_only=True)
        row = db._conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'messages_fts'"
        ).fetchone()
        needs_upgrade = bool(row) and getattr(db, "_db_needs_fts_storage_upgrade")(db._conn)
        interrupted = bool(
            db._conn.execute(
                "SELECT 1 FROM state_meta "
                "WHERE key = 'fts_rebuild_high_water' LIMIT 1"
            ).fetchone()
            or db._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name LIKE 'fts\\_v22\\_trash\\_%' ESCAPE '\\' LIMIT 1"
            ).fetchone()
            or db._conn.execute(
                "SELECT 1 FROM state_meta WHERE key IN "
                "('fts_cjk_rebuild_high_water', 'fts_cjk_stale') LIMIT 1"
            ).fetchone()
        )
    except Exception:
        return
    finally:
        if db is not None:
            with suppress(Exception):
                db.close()
    if not needs_upgrade and not interrupted:
        return

    if interrupted:
        print()
        print("◆ Session database optimization incomplete")
        print(
            "  A previous `hermes sessions optimize-storage` run was "
            "interrupted. Search still works; re-run the command to resume "
            "and finish reclaiming disk:"
        )
        print("    hermes sessions optimize-storage")
        return

    est_reclaim = size_gb * 0.6
    print()
    if mode == "require":
        print("◆ Session database upgrade required")
        print(
            f"  Your search index uses the OLD storage layout and should be "
            f"upgraded. The new layout typically frees ~60% of state.db "
            f"(≈{est_reclaim:.1f} GB of your current {size_gb:.1f} GB) and is "
            "required for continued optimal operation."
        )
    else:
        print("◆ Reclaim ~60% of your session database disk")
        print(
            f"  Your search index uses the old storage layout. Upgrading it "
            f"typically frees ~60% of state.db — about {est_reclaim:.1f} GB "
            f"of your current {size_gb:.1f} GB."
        )
    print("  Run when convenient:  hermes sessions optimize-storage")
    print(
        "  It runs in the foreground with a progress bar, is safe to "
        "interrupt/re-run, and never changes your conversations."
    )


def _ensure_fhs_path_guard() -> None:
    """Ensure /usr/local/bin is on PATH for RHEL-family root non-login shells (su, sudo -s,
    tmux). Mirrors install.sh. Idempotent; no-op on non-Linux/non-root/non-FHS."""
    if sys.platform != "linux":
        return
    try:
        if os.geteuid() != 0:  # windows-footgun: ok — Linux FHS helper, guarded above
            return
    except AttributeError:
        return
    fhs_link = Path("/usr/local/bin/hermes")
    if not fhs_link.is_symlink() and not fhs_link.exists():
        return  # not an FHS-layout install

    # ``bash -i -c`` sources ~/.bashrc but NOT ~/.bash_profile or /etc/profile — the
    # exact scenario where RHEL root loses /usr/local/bin.
    home = os.environ.get("HOME") or "/root"
    try:
        probe = subprocess.run(
            ["env", "-i", f"HOME={home}", f"TERM={os.environ.get('TERM', 'dumb')}",
             "bash", "-i", "-c", "command -v hermes"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return  # no bash or probe hung — don't block the tail on this
    if probe.returncode == 0:
        return  # already on PATH

    path_line = 'export PATH="/usr/local/bin:$PATH"'
    path_comment = "# Hermes Agent — ensure /usr/local/bin is on PATH (RHEL non-login shells)"
    wrote_any = False
    for candidate in (".bashrc", ".bash_profile"):
        cfg = Path(home) / candidate
        if not cfg.is_file():
            continue
        try:
            existing = cfg.read_text(errors="replace", encoding="utf-8-sig")
        except OSError:
            continue
        if any(
            "/usr/local/bin" in line and "PATH" in line and not line.lstrip().startswith("#")
            for line in existing.splitlines()
        ):
            continue
        try:
            with cfg.open("a", encoding="utf-8") as f:
                f.write("\n" + path_comment + "\n" + path_line + "\n")
        except OSError as e:
            print(f"  ⚠ Could not update {cfg}: {e}")
            continue
        print(f"  ✓ Added /usr/local/bin to PATH in {cfg}")
        wrote_any = True
    if wrote_any:
        print("    (reload your shell or run 'source ~/.bashrc' to pick it up)")


def _refresh_cua_driver_after_update() -> None:
    """Reconcile an installed optional package, never a user-selected external binary."""
    import pm

    if not _load_updates_cfg().get("refresh_cua_driver", True):
        return
    if os.environ.get("HERMES_CUA_DRIVER_CMD", "").strip():
        return
    if pm.installed_package("cua-driver", allow_outdated=True) is None:
        return
    if sys.platform == "win32":
        print("\n→ Windows cua-driver refresh deferred (autostart registration requires UAC).")
        print("  Run `hermes computer-use install --upgrade` in an interactive terminal.")
        return
    print("\n→ Preparing pinned cua-driver (Computer Use)...")
    if sys.platform == "darwin":
        from hermes_cli.tools_config_cua import install_cua_driver
        install_cua_driver(show_installer_progress=False)
    else:
        pm.ensure("cua-driver", explicit=True)


def _install_default_tools_after_update() -> None:
    """Give the install its optional default tools: the PM defaults (agent-browser +
    Chromium, cua-driver). Declined packages stay declined (pm/defaults.py); a failed
    download warns and never fails.
    """
    import pm
    from pm.defaults import default_packages
    from pm.install import lazy_installs_allowed, sealed
    from pm.lock import Lockfile
    from pm.paths import lockfile_path

    if sealed() or not lazy_installs_allowed():
        return
    for name in default_packages(Lockfile(lockfile_path()).names()):
        if pm.installed_package(name) is not None:
            continue
        print(f"\n→ Installing {name} (default tool; opt out with `hermes pm install --without {name}`)...")
        try:
            pm.ensure(name, explicit=True)
        except (pm.InstallError, OSError) as exc:
            print(f"  ⚠ {name} was not installed: {exc}")
            print(f"    Retry with: hermes pm install {name}")


def _print_checkpoint_footprint_notice() -> None:
    """Surface a GB-scale /rollback store the user may not know is on."""
    from tools.checkpoint_maintenance import checkpoint_footprint_notice
    notice = checkpoint_footprint_notice()
    if notice:
        print(f"\n\033[1;33mℹ  {notice}\033[0m")


def _migrate_relay_exporter_env() -> None:
    from hermes_cli.relay_plugin_migrate import run_relay_migration_after_update
    run_relay_migration_after_update()


def _print_post_update_notices_and_self_heals() -> None:
    """Best-effort notices (FTS optimize, curator) and self-heals (FHS PATH, CLI launcher
    exposure, cua-driver refresh, default PM tools) that run after the summary."""
    from hermes_cli import _launchers

    for message, step in (
        ('FTS optimize notice failed: %s', _print_fts_optimize_available_notice),
        ('Curator first-run notice failed: %s', _print_curator_first_run_notice),
        ('Curator recent-run notice failed: %s', _print_curator_recent_run_notice),
        ('FHS PATH guard check failed: %s', _ensure_fhs_path_guard),
        ('CLI launcher exposure failed: %s', lambda: _launchers.expose_cli(PROJECT_ROOT)),
        ('cua-driver refresh failed: %s', _refresh_cua_driver_after_update),
        ('Default PM tool install failed: %s', _install_default_tools_after_update),
        ('Checkpoint footprint notice failed: %s', _print_checkpoint_footprint_notice),
        ('Relay exporter migration failed: %s', _migrate_relay_exporter_env),
    ):
        with _best_effort(message):
            step()


def _migrate_sibling_profile_configs() -> list[tuple[str, int, int]]:
    """Migrate every SIBLING profile's config.yaml (the shared checkout serves all profiles),
    NON-INTERACTIVELY via the context-local HERMES_HOME override (never ``os.environ``).
    Returns ``[(name, from_version, to_version), ...]``; never raises. (#91277, #20438.)"""
    from hermes_cli.config import check_config_version, migrate_config
    migrated: list[tuple[str, int, int]] = []
    with _best_effort('Sibling profile enumeration failed: %s'):
        from hermes_constants import (
            get_process_hermes_home, reset_hermes_home_override, set_hermes_home_override)
        from hermes_cli.backup import _sibling_profile_homes
        active_home = Path(get_process_hermes_home())
        for name, profile_home in _sibling_profile_homes(active_home):
            if not (profile_home / "config.yaml").is_file():
                continue  # profile never configured — nothing to migrate
            token = set_hermes_home_override(profile_home)
            try:
                current_ver, latest_ver = check_config_version(raise_on_parse_error=True)
                if current_ver >= latest_ver:
                    continue
                migrate_config(interactive=False, quiet=True)
                after_ver, _ = check_config_version(raise_on_parse_error=True)
                if after_ver > current_ver:
                    migrated.append((name, current_ver, after_ver))
            except Exception as exc:
                logger.debug("Config migration for profile %s failed: %s", name, exc)
            finally:
                reset_hermes_home_override(token)
    return migrated


def _print_items(items, label, key, fallback_key=None):
    if not items:
        return
    print(f"  {label}:")
    shown = items[:8]
    for it in shown:
        if isinstance(it, dict):
            name = it.get(key) or (fallback_key and it.get(fallback_key)) or "?"
            desc = (it.get("description") or "").strip()
        else:
            name, desc = str(it), ""
        print(f"      • {name} — {desc}" if desc else f"      • {name}")
    if len(items) > len(shown):
        print(f"      … and {len(items) - len(shown)} more")


def _ask_configure_new_options(*, assume_yes: bool) -> str:
    """The yes/no answer for "configure new options now?": "y" under --yes, "auto"
    (safe migrations only) when non-interactive, else ``input()``."""
    if assume_yes:
        print("  ℹ --yes: auto-applying config migration (skipping API-key prompts).")
        return "y"
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("  ℹ Non-interactive session — applying safe config migrations.")
        return "auto"
    try:
        return input("Would you like to configure them now? [Y/n]: ").strip().lower()
    except EOFError:
        return "n"
    except UnicodeDecodeError:
        print(
            "  ⚠ Could not read input (encoding issue). Skipping. "
            "Run 'hermes config migrate' manually to configure.")
        return "n"


def _check_and_apply_config_migration(
    *, assume_yes: bool = False
) -> None:
    """Check/apply config migrations. Runs on EVERY completion tail so an interrupted
    update that already pulled code doesn't strand an old config version. See #91360."""
    from hermes_cli.config import check_config_version, migrate_config
    print()
    print("→ Checking configuration for new options...")
    from hermes_cli.config import get_missing_env_vars, get_missing_config_fields
    try:
        missing_env = get_missing_env_vars(required_only=True)
        missing_config = get_missing_config_fields()
        current_ver, latest_ver = check_config_version(raise_on_parse_error=True)
    except Exception as exc:
        logger.debug("Config check during completion failed: %s", exc)
        print("  ⚠️  Could not check config version.")
        print("     Run 'hermes config migrate' to check manually.")
        return

    has_new_options = bool(missing_env or missing_config)
    version_bump_only = not has_new_options and current_ver < latest_ver
    needs_migration = has_new_options or current_ver < latest_ver

    if version_bump_only:
        print()
        print(f"  ℹ Updating config format (v{current_ver} → v{latest_ver})…")
        try:
            _mig_results = migrate_config(interactive=False, quiet=True)
            print("  ✓ Config format updated (no new settings to configure)")
            for _note in _mig_results.get("config_added") or []:
                print(f"  ℹ {_note}")
            for _warn in _mig_results.get("warnings") or []:
                print(f"  ⚠️  {_warn}")
        except Exception as _mig_err:
            print(f"  ⚠️  Config format update failed: {_mig_err}")
            print("     Run 'hermes config migrate' to retry.")
    elif needs_migration:
        print()
        if missing_env:
            print(f"  ⚠️  {len(missing_env)} new required setting(s) need configuration")
            _print_items(missing_env, "New settings", "name")
        if missing_config:
            print(f"  ℹ️  {len(missing_config)} new config option(s) available")
            _print_items(missing_config, "New options", "key")

        print()
        response = _ask_configure_new_options(assume_yes=assume_yes)
        if response in {"", "y", "yes", "auto"}:
            print()
            unattended = assume_yes or response == "auto"
            results = migrate_config(interactive=not unattended, quiet=False)
            if results["env_added"] or results["config_added"]:
                print()
                print("✓ Configuration updated!")
            if unattended and missing_env:
                print("  ℹ API keys require manual entry: hermes config migrate")
        else:
            print()
            print("Skipped. Run 'hermes config migrate' later to configure.")
    else:
        print("  ✓ Configuration is up to date")

    # The migration above touched only the active profile; run the same NON-INTERACTIVE
    # migration per sibling home (never prompt-requiring settings — those wait for the
    # profile's own session).
    with _best_effort('Sibling config migration failed: %s'):
        for _name, _from_ver, _to_ver in _migrate_sibling_profile_configs():
            print(f"  ✓ Profile '{_name}': config format updated (v{_from_ver} → v{_to_ver})")


def run_post_install_maintenance(
    *, assume_yes: bool, pre_update_version: str | None = None,
    completion_message: str | None = None,
) -> bool:
    """Post-build housekeeping and completion, returning the SQLite runtime verdict.

    Ancillary repairs and notices are best-effort; an unsafe runtime withholds success.
    """
    # macOS TCC interpreter anchor; boot-gated — a failed probe leaves the env untouched (#95596).
    try:
        from hermes_cli.macos_tcc_anchor import ensure_tcc_anchor
        ensure_tcc_anchor()
    except Exception:
        logger.debug("macOS TCC anchor refresh skipped", exc_info=True)

    with _best_effort('state.db integrity check failed: %s'):
        _verify_and_restore_state_dbs_post_update()

    # Both shallow history and missing tags can hide the release identity.
    # Refresh them before the completion line and install stamp read it.
    try:
        from hermes_cli.gitlock import fetch_full_commit_graph
        if fetch_full_commit_graph(PROJECT_ROOT, **_no_prompt_git_kwargs()):
            print("  ✓ Fetched release history (commits only) for version identity")
    except (OSError, subprocess.SubprocessError) as exc:
        detail = (getattr(exc, "stderr", None) or str(exc)).strip().splitlines()[-1:] or [type(exc).__name__]
        print(f"  ⚠ Could not refresh release history ({detail[0]}); the version label may be stale or unknown")

    with _best_effort('Model catalog seed failed: %s'):
        from hermes_cli.model_catalog import seed_cache_from_checkout
        if seed_cache_from_checkout(PROJECT_ROOT):
            print("  ✓ Model catalog cache refreshed from checkout")

    with _best_effort('Live plugin catalog cache invalidation failed: %s'):
        _invalidate_live_plugin_catalog_caches()

    with _best_effort('Skills sync failed: %s'):
        print()
        print("→ Syncing bundled skills...")
        _print_bundled_skills_sync_report()

    _sync_profiles_after_update()

    _check_and_apply_config_migration(assume_yes=assume_yes)

    print()
    complete = _print_verified_update_completion(
        completion_message or _update_complete_message(pre_update_version))
    # A multi-profile host whose gateway came back standalone on a guard says so here too.
    with suppress(Exception):
        from hermes_cli.gateway_multiplex_mode import consume_rewritten_notice, recorded_standalone_warning_lines
        for line in [*consume_rewritten_notice(), *recorded_standalone_warning_lines()]:
            print(line)

    _print_post_update_notices_and_self_heals()
    return complete


# ---------------------------------------------------------------------------
# bounded boot maintenance: the quiet counterpart of the tail above
# ---------------------------------------------------------------------------
#
# ``hermes_cli.boot_bootstrap`` runs these once per installed revision and writes their
# result dict into its record. They are the same repairs the install tail does, minus
# anything that prints: a boot path runs under a console that may not exist, and a
# chatty boot is a regression in itself. One failure never stops the rest.

def _backup_path(path: Path, stamp: str) -> Path:
    base = path.with_name(f"{path.name}.bak-{stamp}")
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.bak-{stamp}.{index}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not choose a backup path for {path}")


def _backup_existing(paths) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backups: dict = {}
    for path in paths:
        if not path.is_file():
            continue
        dest = _backup_path(path, stamp)
        shutil.copy2(path, dest)
        backups[path] = dest
    return backups


def _restore_backups(backups: dict) -> list:
    restored = []
    for original, backup in backups.items():
        if not backup.is_file():
            continue
        shutil.copy2(backup, original)
        restored.append(original)
    return restored


def step_migrate_config() -> dict:
    """Migrate config.yaml to the current schema, non-interactively.

    Back up config + .env, migrate, verify the version advanced, restore the
    backups on failure. No-op when the on-disk version is current (the 99%
    case). Boot owns this rollback because a boot must never strand a home on
    a half-written config: nobody is watching for a prompt here.
    """
    from hermes_cli.config import (
        check_config_version,
        get_config_path,
        get_env_path,
        migrate_config,
    )
    from hermes_cli.config_migrations import (
        SUPPORT_FLOOR_VERSION,
        support_floor_message,
    )

    current_ver, latest_ver = check_config_version()
    if current_ver >= latest_ver:
        return {"ok": True, "skipped": "up-to-date"}
    if current_ver < SUPPORT_FLOOR_VERSION:
        # migrate_config() refuses sub-floor configs and leaves the file
        # untouched; warn instead of failing the boot.
        logger.warning("config migration skipped: %s", support_floor_message())
        return {"ok": True, "skipped": "below-support-floor"}

    backups = _backup_existing((get_config_path(), get_env_path()))
    try:
        migrate_config(interactive=False, quiet=True)
    except Exception:
        _restore_backups(backups)
        raise
    post_ver, _ = check_config_version()
    if post_ver < latest_ver:
        restored = _restore_backups(backups)
        raise RuntimeError(
            f"migration did not advance config version to {latest_ver} "
            f"(still {post_ver}); restored: "
            + (", ".join(str(p) for p in restored) if restored else "none")
        )
    return {"ok": True, "migrated": f"{current_ver}->{latest_ver}"}


def step_state_db_guard() -> dict:
    """Verify the active home's state.db is intact.

    Detection only: boot has no pre-build snapshot to restore from, so a
    corrupt db is surfaced loudly in the log rather than silently costing the
    user session search. Read-only, idempotent.
    """
    from hermes_constants import get_hermes_home
    from hermes_cli.backup import verify_sqlite_integrity

    state_path = get_hermes_home() / "state.db"
    if not state_path.exists():
        return {"ok": True, "skipped": "no-state-db"}
    result = verify_sqlite_integrity(state_path, check_header=True, run_pragma=True)
    if result.get("valid"):
        return {"ok": True}
    message = result.get("message", "unknown error")
    logger.error(
        "state.db failed integrity check after a code update: %s — "
        "restore a backup with `hermes backup` tooling or contact support",
        message,
    )
    return {"ok": False, "error": message}


def step_drop_live_plugin_catalog() -> dict:
    """Drop the cached live plugin catalog after a code change.

    A package-manager upgrade or a hand-run ``git pull`` never runs the build
    tail, so without this a pre-change snapshot out-votes the newer in-tree
    catalog for the rest of its TTL (#119340).
    """
    _invalidate_live_plugin_catalog_caches()
    return {"ok": True}


def step_expose_cli() -> dict:
    """Re-publish the ``hermes`` launcher for a tree that moved under an install."""
    from hermes_cli import _launchers

    return _launchers.expose_cli(PROJECT_ROOT)


# Startup skill syncing belongs to each entry point, and the one-time blessed-checkout
# adoption went with the updater it existed for. Boot runs the rest.
BOOT_HOME_STEPS: tuple = (
    ("migrate_config", step_migrate_config),
    ("state_db_guard", step_state_db_guard),
    ("drop_live_plugin_catalog", step_drop_live_plugin_catalog),
    ("expose_cli", step_expose_cli),
)


def run_steps(steps) -> dict:
    """Run steps in order; one failure never stops the rest.

    Returns ``{name: result_dict}``. A raising step records
    ``{"ok": False, "error": str}`` — the caller still writes its record so
    a broken step cannot retrigger the slow path on every boot.
    """
    results: dict = {}
    for name, func in steps:
        try:
            results[name] = func()
        except Exception as exc:
            logger.warning("boot maintenance step %s failed: %s", name, exc)
            results[name] = {"ok": False, "error": str(exc)}
    return results
