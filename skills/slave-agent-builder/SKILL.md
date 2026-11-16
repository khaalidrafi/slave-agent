---
name: slave-agent-builder
description: Build a tailored company or personal assistant on the slave-agent platform (khaalidrafi/slave-agent). Use when the user wants to create, brand, or deploy a customized assistant, whitelabel the platform for an organization, define its persona and capabilities, or prepare a panel embedding such as AdminEverywhere. Covers intake, profile authoring, capability wiring, verification, and handoff.
---

# slave-agent builder

One platform, many assistants. slave-agent ships brand-neutral; a
company turns it into their assistant by writing one profile artifact
and wiring capabilities through configuration. This skill walks that
build end to end. You produce configuration and evidence, never forks
of the platform.

## Current state (read this first)

The profile contract (specs/013) is IMPLEMENTED (commit f793f612c3):
the `persona` package, `persona install <path-or-url>` (validate, land,
activate — an invalid artifact exits nonzero naming the field), golden
renders for banner/help/refusals, and the artifacts directory
`<state>/personas/`. Two deviations from the first spec draft, both
recorded in the code: artifacts live in `personas/` (the state dir's
`profiles/` belongs to upstream's config profiles), and the shop
`total`-folding fixture speaks of a generic reference store (purity
law). The serve boundary applies `persona.redact` PII redaction when
`integration.pii_redact` is true. `slave migrate-state` moves a legacy
state dir once, idempotently. Everything below works as written.

## Before you start

Locate the slave-agent checkout, or clone it:
`git clone https://github.com/khaalidrafi/slave-agent`. Read, in
order:

1. `AGENTS.md` — repo law (docs-first, commit law, secret law).
2. `docs/INTEGRATION-ADMINEVERYWHERE.org` — the purity law and the
   generic surfaces.
3. `specs/013-brandability-profile-contract.org` — the profile
   artifact you will author.
4. `specs/014-admineverywhere-embedding-readiness.org` — only when a
   panel embedding is in scope.

## Laws that never bend

- Purity: no client name, branding, or data model enters the
  slave-agent tree. Client specifics live in the profile artifact,
  which lives in the client's repo. After every change run
  `rg -i "<client-slug>"` over the platform tree and require zero
  hits.
- Secrets: credentials travel as env var NAMES, consumed at call time
  through the secret scope. A secret value in any file you produce is
  a failure, not a warning.
- Read-only default: the shop tools are read-only by construction.
  No write path exists before an approve-before-send gate. Do not
  promise one.
- The product's own mark is generator-owned. Never hand-edit a brand
  string in the platform tree; deployment identity is runtime config.

## Intake (ask these, then stop asking)

1. Company and product names, and the name users will address the
   assistant by.
2. Tone in three adjectives, plus one sentence the assistant would
   plausibly say (this calibrates voice faster than any spec).
3. The five jobs the assistant must do, ranked. For each: what data
   surface it reads (a REST storefront? org memory? a cron schedule?)
   and whether any job must ever WRITE.
4. The integration target: terminal/ACP, an OpenAI-compatible panel
   embed (serve), or both.
5. Who approves outward-facing actions, and what the approval channel
   is.
6. Locale and timezone of the users.

If the user cannot answer a question, apply a default, name it in the
handoff, and move on. Do not stall the build on preference calls.

## Author the profile

Write the profile per specs/013: `identity`, `persona`, `vocabulary`,
`capabilities`, `integration`, `secrets` (names only). Rules of
thumb:

- Persona prose gets an unslop pass before it lands: short
  declarative sentences, no AI vocabulary, no em dashes. Every
  behavioral claim states its source (an intake answer, or a labeled
  default).
- Keep-lists beat prose: "always call it the Service Desk, never
  support" is a vocabulary entry, not a paragraph.
- Map each of the five ranked jobs to a capability block or record it
  as a gap the platform does not cover yet. A gap named in the
  handoff is honest; a silently missing job is a failed build.

## Wire capabilities

- Shop storefront: the `capabilities.shop` block is exactly the
  settings shape in specs/005 (base_url, path layout, filter names,
  status vocabulary, page shape). Money never routes through the
  model; counts carry provenance.
- Panel embedding: follow specs/014. The embedding is in-process: the
  panel depends on the package with its agent extra and feeds the
  profile or brand artifact. ACP is the first-class external surface
  when tool-level control is wanted. The serve endpoint is retired as
  the integration path. The panel side provides hosting, the
  user-to-profile map, RBAC, and secrets as env var names.
- Memory and reminders ride the Org substrate; a human can read and
  edit the state.

## Verify (prove it works, then show it)

1. Schema: the install command validates the profile and exits zero,
   naming the activated profile.
2. Golden renders: banner, help text, and one refusal differ per
   profile with zero code change.
3. Leakage: `rg -i "<client-slug>"` over the platform tree returns
   nothing.
4. Isolation: two profiles in one process answer with their own
   identities and connections.
5. Acceptance conversations: run the top three ranked jobs end to
   end against the real data surface (or a recorded fixture when the
   credential is absent), and paste the transcripts in the handoff.
6. Where a judgment call beats a heuristic and the team runs Jev
   (TypeSafe), batch one request with the open questions as state.
   A failed Jev call is an error, never a "no".

## Hand off

Deliver four artifacts to the client repo: the profile file, the env
var name list with has-it/absent per name, a runbook (install,
serve or ACP invocation, the approval channel), and the acceptance
transcripts. State what the client side provides: hosting, secrets,
RBAC, the user-to-profile map, and the answers to any intake
questions you defaulted.

## Escalation

- A need that does not fit a generic surface goes to the platform
  Lead as a widen-the-surface proposal, never a client special-case
  in the platform tree.
- A contested persona or capability design goes to adversarial
  review (a second model argues the opposite) before the handoff.
- Anything touching the write path or a new secret class stops at the
  Owner.
