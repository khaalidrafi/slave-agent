# CHARTER.md — khaalidrafi/slave-agent team constitution

## Purpose

review, clean and measure vibe-coded projects: turns an AI-generated repo into an Org ledger and walks review -> understand -> comment -> clean with meters and GitHub badges proving a human was here.  The team layer wraps the project; it never rewrites it.
Existing code and conventions outrank the master prompt.

## Canonical law (ONE copy — never embed)

- Master manual: khaalidrafi/agent-team.el `templates/COMMON.org`.
- Global agent law: `ci/AGENTS.md` (the kit submodule, byte-identical
  everywhere).  Project-local law: repo-root AGENTS.md (none yet — do not invent one; the Lead may commission one as board work).
- Chain mechanics: `.github/workflows/agent-team.yml` header + TEAM CI brief.

## Standing team laws

1. LEAD DOESN'T CODE — the Lead cuts specs, dispatches, audits, merges;
   application code flows through the hires (Owner 2026-10-29 #hq).
2. ENV-VAR LAW — credentials travel only as env var NAMES; values live in
   repo secrets / the vault, never in files, chat, commits or logs.
3. Board law — single board `agent-team/TODOS.org`; states TODO, PROGRESS,
   BLOCKED, REVIEW | DONE, CANCELLED, DEFERRED; only the EM flips DONE;
   :EFFORT: from the ladder; no close without clock evidence.
4. Chat law — ONE buffer `agent-team/CHAT.org`, entries appended by command
   only (union merge); the Lead couriers Owner-bound messages to #hq by hand.
5. Branch law — members work `ai/turn-*`; merges land on `ai/main` only
   behind the green gate; CHAT.org union; commit subjects describe the
   change (commit-msg guard).
6. Kit law — agents ride preinstalled in the harness image (canonical kit
   `ci/`, thin repo layer on top); secrets never bake into images.
7. Gateway law — seats talk to providers DIRECT by repo-secret keys; the
   GoModel gateway (khaalidrafi/llmfisher) serves Jev judgment and is
   resolved per job: vars override -> deployment -> localhost -> in-runner
   boot; never a seat dependency.
8. Owner channel — verdicts go to the Owner via the Lead only (OWNER LOCK);
   no chat mirrors (Telegram + Discord retired 2026-10-25/26).

## Role scopes (this repo)

- Rotation + standing seats: see `agent-team/MEMBERS.org` (canonical hiring
  evidence: khaalidrafi/agent-team.el `agent-team/MEMBERS.org`).
- NOT-TOUCH (Lead-owned): `.github/workflows/*`, `.github/scripts/*`,
  `agent-team/CONTROL.org`, `.gitattributes`, the `ci/` submodule pin.
