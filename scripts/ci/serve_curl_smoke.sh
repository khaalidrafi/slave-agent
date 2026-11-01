#!/usr/bin/env bash
# CI curl smoke for the OpenAI-compatible serve surface (TODOS.org board item
# "OpenAI-compatible serving mode"). Boots `serve` on loopback, probes
# /v1/models (read-only catalog) and /v1/chat/completions reachability, then
# tears down. No paid model calls: without a provider key the chat endpoint
# must answer 401/4xx — that IS the contract under test here.
#
# Usage: scripts/ci/serve_curl_smoke.sh   (env: SMOKE_PORT, SMOKE_KEY)
set -euo pipefail

PORT="${SMOKE_PORT:-8901}"
KEY="${SMOKE_KEY:-smoke-key}"
BASE="http://127.0.0.1:${PORT}"

python -m hermes_cli.main serve --host 127.0.0.1 --port "${PORT}" --no-open &
SERVE_PID=$!
trap 'kill "${SERVE_PID}" 2>/dev/null || true' EXIT

# Wait for the listener (up to 30 s).
up=0
for _ in $(seq 1 30); do
  if curl -sf "${BASE}/v1/models" -o /dev/null; then up=1; break; fi
  sleep 1
done
if [ "${up}" -ne 1 ]; then echo "serve did not come up on ${BASE}"; exit 1; fi

# 1) Catalog is a JSON document with a data list.
curl -sf "${BASE}/v1/models" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert isinstance(d.get('data'), list), d
print('models OK:', [m.get('id') for m in d['data']][:3])
"

# 2) Chat endpoint is routed and auth-gated: 200 with a stub provider, or
#    401/403 when the key is not provisioned — never a 404/500.
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE}/v1/chat/completions" \
  -H "Authorization: Bearer ${KEY}" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"ping"}]}')
case "${CODE}" in
  200|401|403) echo "chat/completions reachable (HTTP ${CODE})" ;;
  *) echo "UNEXPECTED HTTP ${CODE} from /v1/chat/completions"; exit 1 ;;
esac

echo "serve curl smoke PASS"
