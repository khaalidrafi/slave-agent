"""``persona`` subcommand parser."""

from __future__ import annotations


def build_persona_parser(subparsers, *, cmd_persona=None) -> None:
    """Attach the ``persona`` subcommand to ``subparsers``."""
    from hermes_cli.persona import cmd_persona as default_cmd

    parser = subparsers.add_parser(
        "persona", help="Deployment personas: one artifact brands the assistant",
        description="Install, list, and activate deployment personas. A persona is one JSON "
            "artifact (identity, persona, vocabulary, capabilities, integration, secrets); "
            "secrets are env var NAMES only. Invalid artifacts fail naming the field.")
    subs = parser.add_subparsers(dest="persona_action")

    install = subs.add_parser("install", help="Validate and land a persona from a path or URL")
    install.add_argument("source", help="path or http(s) URL of the persona JSON")
    install.add_argument("--no-activate", action="store_true",
                         help="land it without making it active")

    subs.add_parser("list", help="List landed personas (* marks the active one)")
    subs.add_parser("show", help="Print the active persona and its banner")

    activate = subs.add_parser("activate", help="Make a landed persona active")
    activate.add_argument("slug", help="slug from `persona list`")

    subs.add_parser("deactivate", help="Return to the product's own identity")

    parser.set_defaults(func=cmd_persona or default_cmd)
