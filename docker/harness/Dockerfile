# khaalidrafi/unslop.el team harness — THIN extension of the canonical CI kit image
# (khaalidrafi/agent-team-ci, ci/docker/harness/Dockerfile).
# INTEGRATION.md section 2: project harnesses EXTEND the canonical image —
# `FROM <base>` + only the layers this repo uniquely needs; a local fork
# without an upstream port is a compliance violation.
#
# Build (from the repo root — the base needs the repo context for the
# ci/AGENTS.md law bake):
#   docker buildx build -f ci/docker/harness/Dockerfile -t agent-team-harness-base:local .
#   docker buildx build -f docker/harness/Dockerfile  -t agent-team-harness:local .
#
# Adds exactly what this team's chain needs and the canonical image lacks:
#   - emacs-nox: the repo IS Emacs Lisp (byte-compile + ERT gate) and the
#     agent-org batch lane is an `emacs --batch' send (Owner R-2-77: CI
#     sends go THROUGH agent-org; Owner 2026-10-27: the SAME agent-org
#     session is reused per member, transcripts preserved in .agent-org/).
#   - the acp package at the PINNED tag agent-org's Package-Requires pins
#     (no-dup law: fetched, never vendored) + the agent-org sources baked
#     at a pinned agent-org commit (same pattern the kit uses for
#     team-chat). The workspace supplies agent-team.el itself.
FROM agent-team-harness-base:local

RUN apt-get update \
 && apt-get install -y --no-install-recommends emacs-nox \
 && rm -rf /var/lib/apt/lists/*

# acp (pinned tag) + agent-org (pinned sha) on the batch lane's load-path:
# AGENT_ORG_LOAD_PATH=/opt/acp-site:/opt/agent-org at run time.
ARG AGENT_ORG_SHA=7b0ee82
RUN mkdir -p /opt/acp-site /opt/agent-org \
 && curl -fsSL "https://raw.githubusercontent.com/xenodium/acp.el/v0.14.3/acp.el" \
      -o /opt/acp-site/acp.el \
 && for f in agent-org.el agent-org-buffer.el agent-org-loader.el \
             agent-org-providers.el agent-org-batch.el; do \
      curl -fsSL "https://raw.githubusercontent.com/khaalidrafi/agent-org/${AGENT_ORG_SHA}/$f" \
        -o "/opt/agent-org/$f" || exit 1; \
    done \
 && test -s /opt/acp-site/acp.el && test -s /opt/agent-org/agent-org-batch.el
