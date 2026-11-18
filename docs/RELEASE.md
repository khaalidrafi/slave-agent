# Release: URL, mark, and the lean-vs-compat token table

Board row "Release URL, mark, token-cost table". This file is the
number a release manager needs; the FORK.org "TODO Decisions still
open" rows it closes are named inline.

## Release URL

Releases are GitHub releases on this repository:

    https://github.com/khaalidrafi/slave-agent/releases

The installer pointer (README, docs) names that URL, never upstream's.
A tag is cut from the generated `ai/slave-agent` branch only (FORK.org:
the branded artifact is the thing users install); `ai/main` carries no
release tags. Assets per release: the source tarball plus, when the
mobile port's phase 2 lands, the Termux `.deb`.

## Mark

The own mark is `assets/icon-master.svg`: a collar — a ring with a
single point facing forward — drawn in the product gold (#CD7F32) on
transparent. The caduceus it replaces was upstream's symbol; the collar
says what the product is (a servant agent) without borrowing a medical
emblem. Regenerate every icon flavor from it:

    python3 scripts/generate_icons.py

(Requires `resvg_py`; the canary-rule test pins that the renderer's tag
rule stays the canonical one.)

## The lean-vs-compat token table

"Lighter" as a number, generated from the overlay itself
(`slave_cli/lean_defaults.py`, 2026-11-17 — the table is the code's
answer, so it cannot drift from the code):

| knob | upstream default | lean default |
|------------------------------------|------------------|--------------|
| mcp.auto_reload_on_config_change | True | False |
| tool_output.max_bytes | 50000 | 16000 |
| tool_output.max_line_length | 2000 | 800 |
| tool_output.max_lines | 2000 | 600 |
| tools.tool_search.listing_max_tokens | 4000 | 1200 |
| tools.tool_search.threshold_pct | 5 | 2 |

What that buys, per turn, in the worst case where every cap binds:

- tool output: at most 16 KB / 600 lines / 800 chars-per-line instead of
  50 KB / 2000 / 2000 — a 3.1x smaller ceiling on what one tool call can
  put in the context window;
- tool-search listing: 1,200 tokens instead of 4,000 — a 2,800-token
  saving on every turn that lists tools;
- MCP config changes no longer trigger an automatic reload cycle.

Every knob reverts with `slave_compat: true` (the overlay's single
switch; `slave_compat` still reads as the old spelling). Live-run
means (tokens per real conversation, both modes) land with the first
release's soak, recorded here; the caps above are the structural
guarantee, not a measurement claim.
