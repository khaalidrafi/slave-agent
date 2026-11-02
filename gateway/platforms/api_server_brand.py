"""Brand/persona layer for business deployments of the API server (``serve``).

A deployment points the platform extra ``brand_file`` (or the env var
``API_SERVER_BRAND_FILE``) at a JSON file; the compiled persona becomes the
default ``ephemeral_system_prompt`` for ``POST /v1/chat/completions`` calls
that carry no system message.  A request-level system message always wins.

Schema (all keys optional, unknown keys ignored)::

    {
      "name": "Freshorama Assistant",
      "tagline": "Fresh groceries, delivered.",
      "voice": ["friendly", "concise"],          // string or list of strings
      "language": "en",                           // reply language
      "facts": ["Ships from Lagos daily"],        // string or list of strings
      "never_do": ["give medical advice"],        // string or list of strings
      "escalation_contact": "support@freshorama.example",
      "system_prefix": "raw text prepended verbatim"
    }

Fail fast: an unreadable or malformed file raises ``ValueError`` at adapter
construction, so an operator never boots with half a persona.  The
integrator guide lives in ``deploy/freshorama/README.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional


def load_brand_prompt(brand_file: Optional[str]) -> str:
    """Compile a brand JSON file into the default system prompt.

    Returns ``""`` when no file is configured.  Raises ``ValueError`` with an
    operator-actionable message when a configured file is missing, unreadable,
    or violates the schema.
    """
    if not brand_file:
        return ""
    path = Path(brand_file).expanduser()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"brand file not found: {path}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"brand file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"brand file must contain a JSON object: {path}")

    prefix = raw.get("system_prefix")
    if prefix is not None and not isinstance(prefix, str):
        raise ValueError("brand system_prefix must be a string")

    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("brand name must be a string")
    tagline = raw.get("tagline")
    if tagline is not None and not isinstance(tagline, str):
        raise ValueError("brand tagline must be a string")
    language = raw.get("language")
    if language is not None and not isinstance(language, str):
        raise ValueError("brand language must be a string")
    escalation = raw.get("escalation_contact")
    if escalation is not None and not isinstance(escalation, str):
        raise ValueError("brand escalation_contact must be a string")

    lines: List[str] = []
    if prefix and prefix.strip():
        lines.append(prefix.strip())
    if name or tagline:
        intro = " ".join(
            part for part in (f"You are {name}." if name else "", tagline or "") if part
        )
        lines.append(intro)

    def _str_list(key: str) -> List[str]:
        value = raw.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return [item for item in value if item.strip()]
        raise ValueError(f"brand {key} must be a string or a list of strings")

    voice = _str_list("voice")
    if voice:
        lines.append("Voice: " + "; ".join(voice) + ".")
    if language and language.strip():
        lines.append(f"Always reply in {language.strip()}.")
    facts = _str_list("facts")
    if facts:
        lines.append("Facts you rely on:\n" + "\n".join(f"- {item}" for item in facts))
    never = _str_list("never_do")
    if never:
        lines.append(
            "Never do any of the following:\n" + "\n".join(f"- {item}" for item in never)
        )
    if escalation and escalation.strip():
        lines.append(
            f"When a request exceeds your scope, refer the user to {escalation.strip()}."
        )
    return "\n\n".join(line for line in lines if line.strip())
