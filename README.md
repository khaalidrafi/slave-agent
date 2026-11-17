<p align="center">
  <img src="assets/banner.png" alt="slave-agent" width="100%">
</p>

# slave-agent

**A customizable agent with the slave feature set — mould it per deployment: a personal assistant, a business assistant, or a developer assistant.**

slave-agent is a deliberately *light* fork of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent): the same agent core, less bulk, cheaper conversations — and every user-facing string, persona and capability renders from one deployment profile, so a tailored assistant is configuration, never a fork.

## What it is

- **The core is a narrow waist.** Talk to the model, run tools, learn from what it did. Everything else — storefront tools, team workflows, platform channels — arrives as a plugin the deployment chooses to install.
- **Light by default, stock behaviour one setting away.** Every lean default is a config knob; `slave_compat: true` reverts the whole set, knob for knob. No optimization without a documented way back.
- **Branding is generated, never hand-edited.** One file (`brand.py`) states the vocabulary; the generator applies it. The branded branch is the base plus exactly one generated commit, so an upstream merge resolves against real code instead of thousands of renames.

## Where it runs

| Surface | How |
| --- | --- |
| CLI + TUI | `slave` |
| Messaging gateways | Telegram, Discord, Slack and ~40 more platform plugins |
| Emacs / any ACP editor | `slave-acp` — the stdio Agent Client Protocol server; the `agent-org` package drives it with Org transcripts and session resume |
| Host applications | the agent core as a Python library through the persona seam — the in-process embedding a panel imports |
| Local OpenAI wire | the serve platform, for deployments that prefer a network boundary |

## Tailoring a deployment

A deployment is a **profile** — identity, persona, vocabulary, capabilities, integrations, secret names (`specs/013`). `slave persona install` validates, lands and self-checks it. The builder skill (`skills/slave-agent-builder/`) walks any agent through intake-to-handoff for a company's tailored assistant, on the purity law: customer names and secrets never enter this tree.

## Install

The package manager owns installing and upgrading — this agent never self-updates. Release artifacts come from this repository's GitHub releases, cut from the generated branded branch only (`docs/RELEASE.md`).

## Doctrine

- `FORK.org` — the fork model: staying mergeable with upstream, the bloat queue.
- `HANDOFF.org` — state of the work and entry points for review.
- `docs/EMACS-ROADMAP-R2-R6.org` — the Emacs and Org surface.
- `docs/MOBILE-PORT.org` — handsets, two-phase contract.
- `specs/` — the numbered spec series (brand, plugins, embedding, pluggability).

License: MIT, inherited from upstream. `contributors/` keeps upstream attribution on purpose.
