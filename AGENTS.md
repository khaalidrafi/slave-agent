# AGENTS.md — slave-agent contributor / agent guide

`ci/templates/TEAMIFY-COMMON-PROMPT.org` (the kit law, pinned by the `ci`
submodule when wired) outranks this file. This file is only what an agent
must not get wrong BEFORE the law boots.

## What this repo is

slave-agent — the Freshorama business-assistant prep (Owner order): a
clean-room slave/worker agent skeleton. FORK.org and HANDOFF.org govern
provenance and the current handoff state — read both before touching
anything. Docs live in docs/. There is no ELisp code gate yet; the branch
in use for handoff work is `handoff`.

## Working rules

- Docs-first repo: changes land as Org files with evidence links; no
  placeholder sections — a section you cannot fill stays OPEN with the
  blocking fact named.
- Keep the handoff branch push-clean: pull --rebase before every push,
  verify the remote tip with `git ls-remote` after.
- No CI chain is wired here yet (no .github/workflows) — do not add one
  without a Lead dispatch; the Freshorama prep defines what the worker
  must do first.

## Commit law (global AGENTS.md applies)

- Author = the model that did the work: `MODEL <MODEL@PROVIDER>`.
- Trailers on every commit: `Co-authored-by: z.ai-agent <z.ai-agent@z.ai>`
  and `Co-authored-by: Khalid Rafi <khaalidrafi@gmail.com>`.
- Never commit to `master`/`main` directly; `ai/<topic>` or `handoff` for
  handoff work.
- Subjects say WHAT changed (3+ words). No `wip`.

## Secrets

Credentials (Freshorama PAT, vault entries) travel as ENV VAR NAMES only —
never in chat, files, commits, or logs. Never echo a secret value anywhere.
