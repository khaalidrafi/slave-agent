"""``persona`` verb: install, list, show, activate, deactivate (specs/013 req. 3).

One-command install: validate, land in the state dir, print the activation
line. An invalid artifact exits nonzero naming the field — never a silent
fallback to defaults.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def cmd_persona(args: Any) -> int:
    from persona import (PersonaError, activate_persona, active_persona,
                         deactivate, install_persona, list_personas, render_banner)
    try:
        if args.persona_action == "install":
            target = install_persona(args.source, activate=not args.no_activate)
            print(f"installed {target}")
            if not args.no_activate:
                print(f"active: {target.stem}")
            else:
                print("not activated; run: persona activate <slug>")
            return 0

        if args.persona_action == "list":
            rows = list_personas()
            current = active_persona()
            slug_now = ""
            if current:
                from persona import persona_slug
                slug_now = persona_slug(current)
            if not rows:
                print("no personas installed; persona install <path-or-url>")
                return 0
            for row in rows:
                mark = "*" if row["slug"] == slug_now else " "
                status = "invalid: " + "; ".join(row["problems"][:2]) if row["problems"] else "ok"
                print(f"{mark} {row['slug']}  {status}")
            return 0

        if args.persona_action == "show":
            data = active_persona()
            if data is None:
                print("no active persona; the product's own identity is in use")
                return 0
            print(render_banner(data))
            print()
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0

        if args.persona_action == "activate":
            activate_persona(args.slug)
            print(f"active: {args.slug}")
            return 0

        if args.persona_action == "deactivate":
            deactivate()
            print("deactivated; the product's own identity is in use")
            return 0

        print("usage: persona {install,list,show,activate,deactivate}", file=sys.stderr)
        return 2
    except PersonaError as exc:
        print(f"persona: {exc}", file=sys.stderr)
        return 1
