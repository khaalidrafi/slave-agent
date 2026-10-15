"""Steward classification and refusal text for sealed install trees.

Adapted from the restack branch's ``installation/tree.py``. Our branch has
no ``installation`` package yet — detection here is rewritten onto the two
facts this branch already ships:

* ``.git`` at the project root says the tree is a checkout the uninstaller
  / updater may mutate.
* The build stamp (``install-stamp.json``, written by
  ``scripts/write_install_stamp.py``) names the steward in
  ``distribution`` (``desktop-app``, ``docker``, ``nix``, or a future
  package manager) for sealed trees.

A sealed tree (no ``.git``) belongs to a steward: only the steward removes
or replaces its code. The refusal messages below always leave the user a
working next step for their data (``hermes uninstall --data`` / the
desktop app's Settings -> About page).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# The fork's brand vocabulary. Two strings in this file name OUR package (the Guix
# one below), and a package name is a fact about the tree, not prose: it has to be
# right in the working branch too, because `guix install` is typed at a shell and
# nothing regenerates it. So it comes from brand.py, per FORK.org's rule that a
# brand string is never hand-written. `brand` is a root module and setup.py ships
# every root module, so this import works in an installed wheel as well.
#
# What does NOT come from brand: the Termux APT name `hermes-agent` further down.
# That is upstream's real published package, so it is a functional KEEP — the same
# class as the `NousResearch/hermes-agent` remote and Meta's `hermes-parser`. The
# generator protects it, and so does this comment.
import brand  # noqa: E402

UPDATE_MECHANISMS = ("self", "app-installer", "electron-updater", "external", "microsoft-store")

STEWARD_DESKTOP = "desktop-app"
STEWARD_DOCKER = "docker"
STEWARD_NIX = "nix"
STEWARD_APT_TERMUX = "apt-termux"
STEWARD_GUIX = "guix"

# A commit build was never published anywhere, so it has no channel to name. Re-homed here
# with the update ladder (FORK.org P0); the Electron shell keeps its own copy of this line in
# ``apps/desktop/electron/updater/external.ts`` because TS cannot import Python.
COMMIT_BUILD_UPDATE_MESSAGE = (
    "This build doesn't get updates. Ask the developer who gave it to you for a new build."
)

# What a sealed tree says when asked to update itself. The updater that used to consult
# this table is gone (FORK.org P0); ``hermes update`` and the dashboard's update tile now
# print these lines instead of doing work. The fallback covers stewards this build does
# not know (a newer package-manager value read by older code).
STEWARD_UPDATE_MESSAGES = {
    STEWARD_DESKTOP: (
        "✗ This Hermes runs from inside the desktop app bundle.\n"
        "\n"
        "Manage updates from within the desktop app.\n"
        "Prefer a self-managed source install? See:\n"
        "  https://hermes-agent.nousresearch.com/docs/user-guide/switching-to-source"
    ),
    STEWARD_NIX: (
        "✗ This Hermes runs from the Nix store.\n"
        "\n"
        "The store path is immutable. Update through your flake:\n"
        "  nix flake update && rebuild your profile or system"
    ),
    STEWARD_APT_TERMUX: (
        "✗ This Hermes runs from a Termux APT package.\n"
        "\n"
        "The package manager owns the code tree. Update with:\n"
        "  pkg upgrade hermes-agent"
    ),
    STEWARD_GUIX: (
        "✗ This Hermes runs from the Guix store.\n"
        "\n"
        "The store path is immutable. Update through your channel:\n"
        f"  guix pull && guix install {brand.SLUG}"
    ),
}

# A git checkout on a Termux host is not ours to update either: the lock
# pins a bionic CPython with no Android wheels, so a source sync would
# build sdists on the phone. The APT package is the only supported shape.
SOURCE_ON_TERMUX_UPDATE_MESSAGE = (
    "✗ This Hermes is a source checkout running under Termux.\n"
    "\n"
    "Source installs are not supported on Termux — `hermes update` would\n"
    "build Python packages on the device. Switch to the APT package:\n"
    "  pkg install hermes-agent"
)
SOURCE_ON_TERMUX_UPDATE_COMMAND = "pkg install hermes-agent"


_STEWARD_UPDATE_FALLBACK = (
    "✗ This Hermes install is managed by {steward}.\n"
    "\n"
    "The tree has no git checkout, so `hermes update` cannot update it.\n"
    "Update it with the tool that installed it."
)

# What the uninstaller says when it refuses to remove code from a sealed
# tree. The steward put the code there; the steward removes it. The
# desktop-app message is per-OS because each OS owns app removal
# differently.
_STEWARD_DELETE_DATA_PREAMBLE = "To delete your Hermes data (chats, configuration, etc),\n"
_STEWARD_DELETE_DATA_CLI = "run:\n$ hermes uninstall --data\n"
_STEWARD_DELETE_DATA_DESKTOP = "Open Hermes Desktop, go to Settings -> About, and delete your data from there.\n"

_STEWARD_UNINSTALL_MESSAGES = {
    STEWARD_DOCKER: (
        "✗ This Hermes runs from a Docker image.\n"
        "\n"
        "There is no code to uninstall — remove the container and image:\n"
        "  docker rm <container> && docker rmi nousresearch/hermes-agent\n"
        "\n" +
        _STEWARD_DELETE_DATA_PREAMBLE +
        _STEWARD_DELETE_DATA_CLI
    ),
    STEWARD_APT_TERMUX: (
        "✗ This Hermes was installed by a Termux APT package.\n"
        "\n"
        "The package manager owns the code tree — uninstall it with:\n"
        "  pkg uninstall hermes-agent\n"
        "\n" +
        _STEWARD_DELETE_DATA_PREAMBLE +
        _STEWARD_DELETE_DATA_CLI
    ),
    STEWARD_NIX: (
        "✗ This Hermes was installed by Nix.\n"
        "\n"
        "The store path is immutable — uninstall it the same way you\n"
        "installed it: remove hermes-agent from your flake / profile\n"
        "(e.g. `nix profile remove`), then rebuild.\n"
        "\n" +
        _STEWARD_DELETE_DATA_PREAMBLE +
        _STEWARD_DELETE_DATA_CLI
    ),
    STEWARD_GUIX: (
        "✗ This Hermes was installed by Guix.\n"
        "\n"
        "The store path is immutable — uninstall it the same way you\n"
        f"installed it: remove {brand.SLUG} from your manifest or profile\n"
        "(e.g. `guix package -u` / edit your `guix` channel config), then reconfigure.\n"
        "\n" +
        _STEWARD_DELETE_DATA_PREAMBLE +
        _STEWARD_DELETE_DATA_CLI
    ),
}

_STEWARD_MANAGED_BY_DESKTOP = "✗ Hermes is managed by the desktop app.\n"

_STEWARD_DESKTOP_UNINSTALL_BY_PLATFORM = {
    "win32": (
        _STEWARD_MANAGED_BY_DESKTOP +
        "\n"
        "Remove the app from Windows Settings → Apps → Installed apps.\n" +
        _STEWARD_DELETE_DATA_PREAMBLE +
        _STEWARD_DELETE_DATA_DESKTOP
    ),
    "darwin": (
        _STEWARD_MANAGED_BY_DESKTOP +
        "\n"
        "Quit the app and drag Hermes.app from Applications to the Trash.\n" +
        _STEWARD_DELETE_DATA_PREAMBLE +
        _STEWARD_DELETE_DATA_DESKTOP
    ),
}

_STEWARD_DESKTOP_UNINSTALL_DEFAULT = (
    _STEWARD_MANAGED_BY_DESKTOP +
    "\n"
    "Delete the Hermes AppImage (or app directory) from wherever you\n"
    "saved it.\n" +
    _STEWARD_DELETE_DATA_PREAMBLE +
    _STEWARD_DELETE_DATA_DESKTOP
)

_STEWARD_UNINSTALL_FALLBACK = (
    "✗ Hermes is managed by {steward}.\n"
    "\n"
    "The tree has no git checkout, so the uninstaller will not remove it.\n"
    "Remove it with the tool that installed it.\n"
    "\n" +
    # A generic package-manager steward has no desktop app, and this
    # refusal prints in a CLI context — point at the CLI data path.
    _STEWARD_DELETE_DATA_PREAMBLE +
    _STEWARD_DELETE_DATA_CLI
)


def steward_update_message(steward: str) -> str:
    """How to upgrade a sealed tree — a message, never an action."""
    message = STEWARD_UPDATE_MESSAGES.get(steward)
    if message is not None:
        return message
    return _STEWARD_UPDATE_FALLBACK.format(steward=steward)


# A git checkout belongs to no package manager, so the CLI's own verb owns its text.
def update_guidance(project_root: Path) -> str:
    """How the install at ``project_root`` gets upgraded, given that it cannot do it itself.

    The one answer every surface prints: the CLI's ``update`` verb, the dashboard's update
    tile and the installed-package proofs all call this. Sealed trees name their package
    manager; a checkout names the manager its owner chose; a commit build has no channel at
    all and says so even when it arrived through a package manager (it was never published
    to one). Mirrors the Electron shell's ``updater/external.ts`` branch for the same stamp.
    """
    from hermes_cli.subcommands.update import UPDATE_POINTER

    if is_commit_build(project_root):
        return COMMIT_BUILD_UPDATE_MESSAGE
    steward = sealed_steward(project_root)
    if steward is None:
        return UPDATE_POINTER
    return steward_update_message(steward)


def steward_uninstall_message(steward: str, platform: "str | None" = None) -> str:
    """The uninstall refusal text for a sealed tree."""
    if steward == STEWARD_DESKTOP:
        key = platform if platform is not None else sys.platform
        return _STEWARD_DESKTOP_UNINSTALL_BY_PLATFORM.get(key, _STEWARD_DESKTOP_UNINSTALL_DEFAULT)
    message = _STEWARD_UNINSTALL_MESSAGES.get(steward)
    if message is not None:
        return message
    return _STEWARD_UNINSTALL_FALLBACK.format(steward=steward)


def read_install_stamp(project_root: Path) -> dict:
    """The build stamp of ``project_root``, or ``{}``.

    Tolerant by design: steward classification must not crash a refusal
    path on a malformed stamp — a tree we cannot prove is ours still
    refuses (see :func:`sealed_steward`), so garbage degrades safely.
    """
    from pm.paths import install_stamp_path

    try:
        data = json.loads(install_stamp_path(project_root).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_bundled_payload(project_root: Path) -> bool:
    """True when ``project_root`` is a bundled desktop payload's ``repo/``.

    THE shape predicate for the sealed-bundle branch, and a mirror of the
    Electron shell's ``installShape() === 'bundled'``: the build stamp is
    the authority, so filesystem coincidences (a sibling ``bin/``, a
    surviving ``apps/desktop/package.json``) can never promote a checkout
    into it. A missing, foreign, or unreadable stamp means NOT bundled.
    """
    try:
        return read_install_stamp(Path(project_root)).get("payload") == "bundled"
    except Exception:  # noqa: BLE001 — a bad stamp must not take a caller down
        return False


def is_commit_build(project_root: Path) -> bool:
    """True when ``project_root`` was built from a commit, not a release tag.

    Re-homed here (FORK.org P0) with the callers that survived the updater's removal: a
    commit artifact has no release feed to compare against, so the dashboard and the
    Termux install proof must both treat it as its own shape.
    """
    return read_install_stamp(Path(project_root)).get("source") == "commit-build"


def sealed_steward(project_root: Path) -> Optional[str]:
    """The steward owning the sealed tree at ``project_root``, or ``None``.

    ``None`` means the tree is a git checkout (``.git`` present — a
    directory, or a worktree/submodule gitfile) and is ours to mutate.
    Everything else is sealed: the stamp's ``distribution`` names the
    steward, and a missing or unreadable stamp gives ``"unknown"`` —
    a tree we cannot prove is ours is not ours to remove.
    """
    root = Path(project_root)
    if (root / ".git").exists():
        return None
    distribution = read_install_stamp(root).get("distribution")
    return distribution if isinstance(distribution, str) and distribution else "unknown"


def classify_install(project_root: Path) -> "tuple[str, bool]":
    """(steward, code_removal_allowed) for the tree at ``project_root``.

    A git checkout reports ``("git", True)``; a sealed tree reports its
    steward and ``False``. Used by ``gui_install_summary`` so the desktop
    UI can gate its destructive options on the same ladder the CLI uses.
    """
    steward = sealed_steward(project_root)
    if steward is None:
        return ("git", True)
    return (steward, False)
