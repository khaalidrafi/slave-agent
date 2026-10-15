"""``hermes update`` is a pointer to the package manager.

This fork does not self-update (see FORK.org: on Guix/Nix the package manager
owns installs; a self-updater would fight a read-only store path and
re-resolve a dependency closure we did not choose). The updater subsystem --
fleet checkouts, stashes, restart handoffs, receipts, windows app-installer
channels -- was removed in P0 of the light-core queue; this stub keeps the
parser wiring in ``hermes_cli/main.py`` and the ``/update`` slash command
harmless instead of crashing.
"""

from __future__ import annotations


UPDATE_POINTER = (
    "Hermes does not self-update.\n"
    "Upgrade it with your package manager, e.g.:\n"
    "  Guix:  guix pull && guix install hermes-agent (or reconfigure your home)\n"
    "  Nix:   nix profile upgrade '.*hermes.*'\n"
    "Upstream releases: https://github.com/NousResearch/hermes-agent"
)


def cmd_update(args=None) -> None:  # noqa: ARG001 - args accepted for parser wiring
    """Print the package-manager pointer and exit 0 (a refusal is not an error)."""
    print(UPDATE_POINTER)


def build_update_parser(subparsers, *, cmd_update=cmd_update) -> None:
    """Attach the stub ``update`` subcommand to ``subparsers``."""
    parser = subparsers.add_parser(
        "update",
        help="This build does not self-update; prints the package-manager command",
        description=(
            "The package manager that installed Hermes owns upgrading it. "
            "Running this command only prints the right command for your system."
        ),
    )
    parser.set_defaults(func=cmd_update)
