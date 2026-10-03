"""Single source of truth for this fork's brand vocabulary.

Upstream (NousResearch/hermes-agent) is rebranded by ``scripts/rebrand.py``, which
rewrites *occurrences in text* (string literals, docs, configs) so that the fork
stays re-brandable after every upstream merge instead of carrying a one-shot diff.
Anything new that needs a brand name should import it from here rather than
hardcoding a word, so a future rename stays a two-file change.

``PRODUCT`` is the name as it is written everywhere — including at the start of a
sentence. It is a tool name in CLI style (like ``npm`` or ``gh``), not a title, so
``SLUG`` and ``PRODUCT`` differ only in that the display form is the same word.
"""

PRODUCT: str = "slave-agent"
SLUG: str = "slave-agent"            # PyPI / npm / repository directory name
MODULE: str = "slave_agent"          # python identifier form
CLI: str = "slave"                   # primary console command
HOME_ENV: str = "SLAVE_AGENT_HOME"   # preferred override for the state dir
UPSTREAM: str = "NousResearch/hermes-agent"
TAGLINE: str = "the agent that learns its master"

# What the product claims about itself, in one breath. Used by README/banner/docs.
PITCH: str = (
    "A servant agent that cares about its master: it gets lighter and sharper with "
    "use, stays off your machine's critical path, and can drive other coding agents "
    "with what it has learned about you."
)

__all__ = [
    "PRODUCT", "SLUG", "MODULE", "CLI",
    "HOME_ENV", "UPSTREAM", "TAGLINE", "PITCH",
]
