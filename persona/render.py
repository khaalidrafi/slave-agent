"""Rendering: every user-facing string a deployment can shape (specs/013 req. 2).

Three renders are the contract's proof surface: the banner nameplate, the
slash-command help header, and one refusal. All three derive from the SAME
artifact with zero code change, which is what acceptance criterion 2 tests
with two fixture personas. The persona compiler reuses the semantics the
serve side already pinned (api_server_brand.py): fail fast on malformed
input, and a request-level system message always wins — compilation here
never sees a request, so the precedence law lives at the callers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def compile_persona(data: Dict[str, Any]) -> str:
    """Compile an artifact into a default system prompt.

    The shape mirrors ``gateway/platforms/api_server_brand.py`` so the library
    seam and the serve surface produce the same persona from the same file —
    two compilers drifting apart would mean a panel-embedded assistant and a
    serve-deployed one answer with different voices.
    """
    identity = data.get("identity") or {}
    persona = data.get("persona") or {}
    lines: List[str] = []

    prefix = persona.get("system_prefix")
    if prefix:
        lines.append(str(prefix).strip())
        lines.append("")

    name = identity.get("assistant") or identity.get("product")
    if name:
        lines.append(f"You are {name}.")
    if identity.get("company"):
        lines.append(f"You assist people working with {identity['company']}.")
    if identity.get("tagline"):
        lines.append(f"{identity['tagline']}")

    voice = _as_list(persona.get("voice"))
    if voice:
        lines.append(f"Voice: {', '.join(voice)}.")
    tone = _as_list(persona.get("tone"))
    if tone:
        lines.append(f"Tone: {', '.join(tone[:3])}.")
    if persona.get("language"):
        lines.append(f"Reply in {persona['language']}.")

    facts = _as_list(persona.get("facts"))
    if facts:
        lines.append("")
        lines.append("Facts you may rely on:")
        lines.extend(f"- {fact}" for fact in facts)

    style = _as_list(persona.get("style"))
    if style:
        lines.append("")
        lines.append("Style rules:")
        lines.extend(f"- {rule}" for rule in style)

    never = _as_list(persona.get("never_do"))
    if never:
        lines.append("")
        lines.append("Never:")
        lines.extend(f"- {item}" for item in never)

    vocabulary = data.get("vocabulary") or {}
    keep = _as_list(vocabulary.get("keep"))
    if keep:
        lines.append("")
        lines.append("Always use these terms exactly:")
        lines.extend(f"- {term}" for term in keep)
    banned = _as_list(vocabulary.get("banned"))
    if banned:
        lines.append("")
        lines.append("Never emit these terms:")
        lines.extend(f"- {term}" for term in banned)

    if persona.get("escalation_contact"):
        lines.append("")
        lines.append(f"Escalate to: {persona['escalation_contact']}")
    return "\n".join(lines).strip()


def render_banner(data: Dict[str, Any]) -> str:
    """The nameplate a terminal shows: assistant name and tagline on one rule."""
    identity = data.get("identity") or {}
    name = identity.get("assistant") or identity.get("product") or "assistant"
    tagline = identity.get("tagline") or ""
    inner = f"{name} — {tagline}" if tagline else str(name)
    rule = "═" * (len(inner) + 2)
    return f"╔{rule}╗\n║ {inner} ║\n╚{rule}╝"


def render_help(data: Dict[str, Any]) -> str:
    """The slash-command help header, addressed by the assistant's name."""
    identity = data.get("identity") or {}
    name = identity.get("assistant") or "assistant"
    return (f"{name} — commands\n"
            "  /shop    read the storefront\n"
            "  /remind  schedule a reminder\n"
            "  /recap   summarize this conversation")


def render_refusal(data: Dict[str, Any], what: str) -> str:
    """One refusal in the deployment's voice; the shape every refusal uses."""
    identity = data.get("identity") or {}
    persona = data.get("persona") or {}
    name = identity.get("assistant") or "assistant"
    style = persona.get("refusal_style") or "plain"
    first = {
        "plain": f"I can't {what}.",
        "apologetic": f"Sorry — I can't {what}.",
        "formal": f"I am unable to {what}.",
    }.get(str(style).lower(), f"I can't {what}.")
    contact = persona.get("escalation_contact")
    if contact:
        return f"{first} If you need it anyway, contact {contact}."
    signature = persona.get("signature")
    if signature:
        return f"{first}\n{signature}"
    return first


def persona_nameplate(data: Optional[Dict[str, Any]]) -> Optional[tuple[str, str]]:
    """(name, tagline) for the banner, or None when no persona is active.

    ``hermes_cli.banner`` calls this: the product's own wordmark stays the
    default (generator-owned, specs/002); an active deployment persona
    replaces it at runtime (specs/013 req. 2) without touching brand.py.
    """
    if not data:
        return None
    identity = data.get("identity") or {}
    name = identity.get("assistant") or identity.get("product")
    if not name:
        return None
    return str(name), str(identity.get("tagline") or "")
