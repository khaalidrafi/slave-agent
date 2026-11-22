"""Profile schema and validation (specs/013, as landed).

A deployment persona is ONE JSON artifact: identity, persona, vocabulary,
capabilities, integration, secrets. Validation is a first-class failure — an
invalid artifact names the offending field and exits nonzero, never falling
back to defaults silently (req. 6). Secrets travel as env var NAMES; a value
in the file is a schema violation, not a warning (req. 1).

The artifact lands at ``<state>/personas/<slug>.json``. The spec's first draft
said ``profiles/<name>.json``, but the state dir's ``profiles/`` already
belongs to upstream's config profiles (alternate homes, see
``slave_cli.profiles``); sharing it would make a deployment persona and a
config profile fight over one directory, so the deployment tier gets
``personas/`` and the correction is recorded here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

TOP_LEVEL_KEYS = ("identity", "persona", "vocabulary", "capabilities", "integration", "secrets")

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Shapes no purpose string ever has but leaked credentials do. Checked against
# the whole serialized artifact, so a secret hiding in any string fails.
_SECRET_SHAPES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|rk|pk)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\b"),
)


class PersonaError(ValueError):
    """An invalid deployment artifact. ``problems`` names every field that failed."""


def _expect(problem: List[str], field: str, value: Any, *types: type, optional: bool = True) -> Any:
    if value is None and optional:
        return None
    if not isinstance(value, types):
        want = " or ".join(t.__name__ for t in types)
        problem.append(f"{field}: expected {want}, got {type(value).__name__}")
        return None
    return value


def _expect_str_list(problem: List[str], field: str, value: Any, limit: int = 0) -> None:
    if value is None:
        return
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problem.append(f"{field}: expected a string or list of strings")
        return
    if limit and len(value) > limit:
        problem.append(f"{field}: at most {limit} entries, got {len(value)}")


def validate_persona(data: Any) -> List[str]:
    """Return the list of problems; empty means the artifact is valid."""
    problems: List[str] = []
    data = _expect(problems, "persona file", data, dict, optional=False) or {}

    unknown = sorted(set(data) - set(TOP_LEVEL_KEYS))
    if unknown:
        problems.append(f"unknown top-level key(s): {', '.join(unknown)} "
                        f"(known: {', '.join(TOP_LEVEL_KEYS)})")

    identity = _expect(problems, "identity", data.get("identity"), dict) or {}
    for key in ("company", "product", "assistant", "tagline", "locale", "timezone"):
        _expect(problems, f"identity.{key}", identity.get(key), str)

    persona = _expect(problems, "persona", data.get("persona"), dict) or {}
    _expect_str_list(problems, "persona.tone", persona.get("tone"), limit=3)
    for key in ("language", "refusal_style", "signature", "system_prefix", "escalation_contact"):
        _expect(problems, f"persona.{key}", persona.get(key), str)
    _expect_str_list(problems, "persona.style", persona.get("style"))
    # The brand-JSON keys ride here: the artifact extends the landed mechanism
    # (gateway/platforms/api_server_brand.py), never forks it (req. 1).
    _expect_str_list(problems, "persona.voice", persona.get("voice"))
    _expect_str_list(problems, "persona.facts", persona.get("facts"))
    _expect_str_list(problems, "persona.never_do", persona.get("never_do"))

    vocabulary = _expect(problems, "vocabulary", data.get("vocabulary"), dict) or {}
    _expect_str_list(problems, "vocabulary.keep", vocabulary.get("keep"))
    _expect_str_list(problems, "vocabulary.banned", vocabulary.get("banned"))

    capabilities = _expect(problems, "capabilities", data.get("capabilities"), dict) or {}
    shop = _expect(problems, "capabilities.shop", capabilities.get("shop"), dict)
    if isinstance(shop, dict):
        # The shop block is exactly the settings shape of specs/005: a superset
        # check, not a second schema.
        for key in ("base_url", "token_env", "adapter"):
            _expect(problems, f"capabilities.shop.{key}", shop.get(key), str)

    integration = _expect(problems, "integration", data.get("integration"), dict) or {}
    surfaces = _expect(problems, "integration.surfaces", integration.get("surfaces"), list)
    if isinstance(surfaces, list):
        bad = [s for s in surfaces if s not in ("library", "acp")]
        if bad:
            problems.append(f"integration.surfaces: unknown surface(s) {bad}; known: library, acp")
    for key in ("banner", "pii_redact"):
        _expect(problems, f"integration.{key}", integration.get(key), bool)

    secrets = _expect(problems, "secrets", data.get("secrets"), dict) or {}
    for name, purpose in secrets.items():
        if not isinstance(name, str) or not _ENV_NAME_RE.match(name):
            problems.append(f"secrets.{name}: a secret's key must be an ENV VAR NAME "
                            f"(uppercase letters, digits, underscores)")
        _expect(problems, f"secrets.{name}", purpose, str)

    import json
    try:
        blob = json.dumps(data)
    except (TypeError, ValueError):
        problems.append("persona file: not JSON-serializable")
    else:
        for pattern in _SECRET_SHAPES:
            if pattern.search(blob):
                problems.append("secrets: a VALUE that looks like a credential is in the file; "
                                "secrets travel as env var names only")
                break
    return problems


def require_valid(data: Any) -> Dict[str, Any]:
    """Validate or raise :class:`PersonaError` naming every problem."""
    problems = validate_persona(data)
    if problems:
        raise PersonaError("; ".join(problems))
    assert isinstance(data, dict)
    return data


def persona_slug(data: Dict[str, Any]) -> str:
    """Filesystem slug for an artifact: company name, dashed, plus a content tail.

    The tail keeps two different companies that happen to share a name from
    overwriting each other, and makes a re-install of changed content a NEW
    file instead of a silent in-place mutation.
    """
    import hashlib
    import json
    raw = (data.get("identity") or {}).get("company") or "default"
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).lower()).strip("-") or "default"
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:6]
    return f"{slug[:40]}-{digest}"
