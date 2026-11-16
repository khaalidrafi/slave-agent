"""PII redaction at the prompt boundary (board: group-chat capabilities).

Pure functions, no I/O: the caller owns the boundary (the serve adapter's
request path). Redaction is opt-in per deployment (persona
``integration.pii_redact`` or the ``platforms.api_server.pii_redact`` extra);
an unconfigured host never rewrites a user's words. What is redacted: things a
person cannot unsay — card numbers, private keys and tokens, e-mail addresses,
phone numbers. The replacement keeps the SHAIR so a human reviewing logs can
still tell two mentions of the same value apart.
"""

from __future__ import annotations

import re
from typing import Iterable, Tuple

# 13-19 digits with spaces/dashes between them: the PAN range. Deliberately
# not Luhn-checked — a redactor that only catches VALID cards teaches everyone
# that an invalid-looking number is safe to paste.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# +countrycode then 7-13 digits, or a plain 10-13 digit run with separators.
# Short digit runs (dates, order ids) must survive: 7 is the floor.
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[ -]?)?(?:\(?[0-9]\)?[ -]?){10,13}")
_SECRET_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk|rk|pk)_[A-Za-z0-9]{16,}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
    r"|\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]*\b",
    re.S,
)


def _share(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:6]


def redact_text(text: str, rules: Iterable[str] = ("card", "secret", "email", "phone")) -> Tuple[str, int]:
    """Return (redacted_text, count). Order: most specific pattern first."""
    rules = tuple(rules)
    count = 0

    def _sub(pattern: re.Pattern, label: str) -> None:
        nonlocal text, count
        def repl(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"[{label}:{_share(m.group(0))}]"
        text = pattern.sub(repl, text)

    # Secrets before cards and phones: a token's digit tail would otherwise be
    # half-eaten by the card rule and leak its shape.
    if "secret" in rules:
        _sub(_SECRET_RE, "secret")
    if "card" in rules:
        _sub(_CARD_RE, "card")
    if "email" in rules:
        _sub(_EMAIL_RE, "email")
    if "phone" in rules:
        _sub(_PHONE_RE, "phone")
    return text, count
