"""``migrate-state`` subcommand parser."""

from __future__ import annotations


def build_migrate_state_parser(subparsers, *, cmd_migrate_state=None) -> None:
    """Attach the ``migrate-state`` subcommand to ``subparsers``."""
    from hermes_cli.state_migrate import cmd_migrate_state as default_cmd

    parser = subparsers.add_parser(
        "migrate-state", help="One-shot state-dir move from the legacy name",
        description="Moves the state directory from its legacy name to this build's default, "
            "once and idempotently. A conflict (both exist, target non-empty) is reported, "
            "not overridden. HERMES_HOME must be unset: explicit configuration is never "
            "second-guessed.")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the move without performing it")
    parser.set_defaults(func=cmd_migrate_state or default_cmd)
