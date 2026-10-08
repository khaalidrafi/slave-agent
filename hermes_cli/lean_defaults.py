"""This fork's lean config overlay, and the single switch that turns it off.

Upstream's defaults are tuned for whoever installs with ``hermes update`` and never looks
at a token bill. This fork ships as a package to people who do, so the values it starts
with are lighter. ``config_defaults.py`` is deliberately *not* edited: it stays
byte-identical to upstream, which (a) keeps merges on the most-conflicted file in the tree
cheap and (b) makes ``hermes_compat: true`` a subtraction rather than a patch -- the stock
Hermes value is still whatever ``DEFAULT_CONFIG`` says, and this file only names what we
lower.

Precedence is mechanical, with no special cases:

    explicit value in the user's config.yaml  >  this overlay  >  upstream default

The overlay is applied to the *merged* config and only on paths the user's own file does
not name, so a user who set one knob keeps it while ``hermes_compat`` still removes the
rest of the overlay in one go.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

#: Top-level key that puts the user back on stock Hermes values.
COMPAT_KEY = "hermes_compat"

# Dotted path -> the value this fork ships instead of upstream's. Kept to knobs whose
# upstream value is a *cost* rather than a preference: each one either multiplies what the
# model is charged for or breaks the prompt cache, and each is named in the comment.
LEAN_DEFAULTS: Dict[Tuple[str, ...], Any] = {
    # A 50,000-char terminal cap is ~12-15K tokens of output per call, sent on every turn
    # that keeps it. Head+tail truncation still holds, so the loss is the middle of a long
    # dump -- which is the part nobody reads.
    ("tool_output", "max_bytes"): 16_000,
    # read_file's per-call `limit` clamp and its per-line cap, same arithmetic: a page of
    # source that costs 2000 lines x 2000 chars is a context bill, not a reading
    # convenience. Re-ask with a bigger limit when you actually need the whole file.
    ("tool_output", "max_lines"): 600,
    ("tool_output", "max_line_length"): 800,
    # Tool Search's catalog listing rides in the bridge tool's description, so it is paid
    # on every API call for the life of the conversation. A 2% budget is still enough to
    # name the servers; the model can ask for more with `tool_search`.
    ("tools", "tool_search", "threshold_pct"): 2,
    ("tools", "tool_search", "listing_max_tokens"): 1_200,
    # Reloading MCP servers on every config edit rebuilds the tool surface, which
    # invalidates the provider prompt cache for the whole conversation. The watcher still
    # detects the change and prints /reload-mcp guidance, so what this costs is one
    # keystroke -- and it stops a config tweak from silently doubling the next turn's cost.
    ("mcp", "auto_reload_on_config_change"): False,
}


def _truthy(value: Any) -> bool:
    """Accept the spellings a human actually types into a YAML bool field."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def hermes_compat_enabled(user_config: Optional[Dict[str, Any]]) -> bool:
    """True when the user asked for stock Hermes behaviour, overlay off.

Read from the *user's* file only. A compat flag in ``DEFAULT_CONFIG`` would make the
overlay self-disabling, and in a managed overlay (the enterprise case) it is the operator's
choice, so the managed section is consulted through the same argument the caller built."""
    return bool(user_config) and _truthy(user_config.get(COMPAT_KEY))


def _user_named(user_config: Optional[Dict[str, Any]], path: Sequence[str]) -> bool:
    """True when the user's own file spells a value at ``path``.

A parent that is not a mapping (``tool_output: 5``) counts as naming nothing: there is no
leaf to respect, and the overlay then supplies the dict-shaped value the readers expect."""
    node: Any = user_config
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return False
        node = node[segment]
    return True


def apply_lean_defaults(config: Dict[str, Any],
                        user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Write the overlay into ``config`` on every path the user left alone. Mutates and
    returns ``config``, which the caller owns before it reaches the load cache. A no-op
    when ``hermes_compat: true``."""
    if hermes_compat_enabled(user_config):
        return config
    for path, lean_value in LEAN_DEFAULTS.items():
        if _user_named(user_config, path):
            continue
        parent = config
        for segment in path[:-1]:
            child = parent.get(segment)
            if not isinstance(child, dict):
                child = {}
                parent[segment] = child
            parent = child
        parent[path[-1]] = lean_value
    return config


__all__ = ["COMPAT_KEY", "LEAN_DEFAULTS", "apply_lean_defaults", "hermes_compat_enabled"]
