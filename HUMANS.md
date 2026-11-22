# HUMANS.md — slave-agent

A guide for humans navigating and developing this codebase. Written
2026-11-18 per the org-wide rule that every agent-developed repo
carries one.

## What this is

A deliberately light fork of NousResearch/hermes-agent: the same
agent core, less bulk, cheaper conversations — and every user-facing
string, persona and capability renders from ONE deployment profile,
so a tailored assistant (personal, business, developer) is
configuration, never a fork. The core is a narrow waist: talk to the
model, run tools, learn from what it did. Everything else (storefront
tools, team workflows, platform channels) arrives as a plugin the
deployment chooses.

Surfaces: CLI/TUI (`slave`), ~40 messaging gateways, ACP editors
(`slave-acp` — driven by the `agent-org` package), host applications
(the in-process persona seam a panel imports), and a local OpenAI
wire (the serve platform).

## The fork model (read FORK.org before your first change)

This fork renames upstream end to end, and the rename is GENERATED,
not carried: `brand.py` states the vocabulary, `scripts/rebrand.py`
applies it, and the branded branch `ai/slave-agent` is the base plus
exactly ONE generated commit ("brand: regenerate for upstream
<sha>"). That is why upstream merges resolve against real code
instead of thousands of renames. `scripts/fork-sync.sh` runs the
whole sync: merge upstream (never squashed — every upstream commit
lands individually), regenerate the brand, run the verify gate.

Branch topology: `main`/`handoff` trunks, `ai/main` (agent work),
`ai/slave-agent` (the branded branch releases are cut from,
`docs/RELEASE.md`), `upstream/main` (a read-only tracker ref of
where we have merged). Upstream syncs ride merge commits; doctrine
conflicts (`git rm` wins over upstream re-adding bloat) are recorded
in FORK.org's bloat queue.

## Code map (the load-bearing parts)

| Path | Role |
|---|---|
| `agent/`, `slave*/`, `slave_*`, `run_agent.py`, `cli.py` | The core loop: model conversation, tool execution, learning. `slave_*` names are upstream heritage; `slave_*` are fork-owned modules. |
| `acp_adapter/` | `slave-acp`: the stdio Agent Client Protocol server editors drive. |
| `gateway/`, `plugins/`, `plugin-catalog/`, `optional-mcps/` | The plugin surface: platform channels, capabilities, the catalog a deployment chooses from. |
| `persona/`, `specs/` | The deployment-profile seam (specs/013) and the numbered spec series (brand, plugins, embedding, pluggability). |
| `providers/`, `toolsets.py`, `model_tools.py` | Model providers and tool registration. |
| `persistence/`, `sqlite_support.py`, `session_*.py` | State: sessions, retention, rescue, rules. |
| `brand.py` + `scripts/rebrand.py` | The brand vocabulary and the generator (see the fork model). |
| `scripts/fork-sync.sh` | The upstream sync lane (merge + regenerate + verify). |
| `scripts/kernel_floor*` | Import-floor guard: the set of modules allowed to be imported at kernel startup; grows only by recorded decision. |
| `scripts/check`, `scripts/boundary_lint*`, `scripts/check_*.py` | The many static gates (case collisions, Windows footguns, packaged imports, detached spawns...). |
| `skills/` | The agent-facing skills, including `slave-agent-builder` (the canonical copy the kit vendors). |
| `mobile/`, `docs/MOBILE-PORT.org` | The mobile answer: Termux is developer-lane only; the real path is the native Phase-2 port (seams: AdminEverywhere APK + specs/014, three bionic recompiles, kill criteria). |
| `FORK.org`, `HANDOFF.org`, `SOUL.md`, `TODOs.org`, `AGENTS.md` | Doctrine: fork model, work state, product character, queue, law. |
| `agent-team/`, `ci/` | Team state and the agent-team-ci kit submodule. |
| `docs/` | RELEASE, EMACS-ROADMAP, MOBILE-PORT and the rest of the document series. |
| `contributors/` | Upstream attribution, kept on purpose. |

## Invariants and gotchas

- **The rename is generated.** Never hand-edit a branded string; fix
  `brand.py` and regenerate. The branded branch must stay
  base + exactly one generated commit.
- **Upstream merges are never squashed** (Owner order 2026-11-18):
  every upstream commit lands individually; a merge that would pile
  commits into one is a law violation.
- **Attribution is sticky** (Owner order 2026-11-18): Flash's commits
  stay Flash; the acting brain commits under its own identity; member
  seats carry their own work. The 2026-11-18 org-wide rewrite that
  absorbed Flash's commits into the Lead identity was reversed
  (trees restored byte-identical) — never repeat it.
- **No self-update**: the package manager owns installing and
  upgrading; the largest deleted subsystem exists precisely because
  of this rule. `slave_compat: true` reverts lean defaults knob for
  knob — every optimization keeps a documented way back.
- **Purity law**: customer names and secrets never enter this tree
  (the builder skill enforces it per deployment).
- Tests: `pytest` (Python), `tests-js` (node); the check lanes live
  under `scripts/check*`. CI pins the agent-team-ci kit (`ci/`
  submodule pointer).
- Static verification is the floor in sandboxes without a venv: say
  so when that is all you ran.

## Developing

```sh
# Upstream sync (the whole lane):
UPSTREAM_REMOTE=upstream bash scripts/fork-sync.sh

# Static gates used before landing:
python3 -m compileall -q .            # syntax floor
python3 scripts/kernel_floor --check-imports
python3 scripts/rebrand.py --lint --blind

# Tests (when the environment supports it):
pytest
```

Branch law: agent work lands on `ai/main`; the branded branch is
regenerated, not accumulated; releases are cut from `ai/slave-agent`
only.
