# Freshorama integration guide — slave-agent as your business assistant

`serve` exposes the agent as an **OpenAI-compatible chat API**
(`POST /v1/chat/completions`, `GET /v1/models`).  Freshorama customizes it
as its business assistant **without touching agent code**: a brand file
sets the persona, environment variables set the addresses and keys, and any
OpenAI-compatible front end (chat widget, CRM integration, n8n/Zapier,
LibreChat, Open WebUI) can talk to it.

## 1. Quickstart

```bash
# from the repo root
python -m hermes_cli.main serve --host 127.0.0.1 --port 8080 --no-open
```

The server prints its address.  Verify it is alive:

```bash
curl -s http://127.0.0.1:8080/v1/models | head -c 400; echo
```

## 2. Environment surface (everything rides env — nothing is baked into files)

| Variable | Purpose | Default |
| --- | --- | --- |
| `API_SERVER_KEY` | Bearer key clients must send (`Authorization: Bearer …`). Requests without it get `401`; session continuity (`X-Hermes-Session-Id`) requires it. | unset (auth disabled — set it in production) |
| `API_SERVER_HOST` | Bind address. Keep `127.0.0.1` unless a reverse proxy fronts the server. | loopback default |
| `API_SERVER_PORT` | Listen port. | `8080` |
| `API_SERVER_BRAND_FILE` | Path to the brand JSON (persona). See §3. | unset (no default persona) |
| `API_SERVER_MODEL_NAME` | Model name advertised on `/v1/models` and accepted from clients. | gateway default |
| `HERMES_HOME` | State directory (session DB, memories). Give the service its own. | platform default |

Equivalent per-platform `config.yaml` keys (`platforms.api_server`): `key`,
`host`, `port`, `brand_file`, `model_name` — config wins over env.

## 3. Brand file (the customization point)

Copy `brand.example.json` beside your deployment and edit it:

```bash
cp deploy/freshorama/brand.example.json /etc/freshorama/brand.json
export API_SERVER_BRAND_FILE=/etc/freshorama/brand.json
```

Schema — all keys optional; unknown keys are ignored:

| Key | Type | Effect |
| --- | --- | --- |
| `name` | string | "You are {name}." opening line |
| `tagline` | string | one-line mission appended to the opening |
| `voice` | string or string list | tone directives ("friendly; concise") |
| `language` | string | reply-language directive ("Always reply in en.") |
| `facts` | string or string list | business facts the assistant relies on |
| `never_do` | string or string list | hard refusals |
| `escalation_contact` | string | where to point out-of-scope requests |
| `system_prefix` | string | raw text prepended verbatim (full manual override) |

**Precedence:** the brand persona is the *default*.  If a request carries a
`system` message, that message replaces the default for that request —
your front end can always override per call.

**Rules of the file:** it is data, not code (JSON only).  Never put
credentials inside it.  A malformed file fails the server at boot with a
clear error — fix it, do not disable the check.

## 4. Client contract

```bash
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer $API_SERVER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"What produces are in season?"}]}'
```

- Non-stream → OpenAI `chat.completion` JSON.  `"stream": true` → SSE frames
  ending with `data: [DONE]` (strict-OpenAI mode; no Hermes-specific frames).
- Optional headers: `X-Hermes-Session-Id` continues a conversation server-side
  (requires `API_SERVER_KEY`); `X-Hermes-Session-Key` scopes long-term memory.
- Wire contract is pinned by `tests/gateway/platforms/test_serve_openai_contract.py`
  and smoke-checked by `scripts/ci/serve_curl_smoke.sh`.

## 5. Running it as a service (systemd sample)

```ini
[Unit]
Description=Freshorama business assistant (slave-agent serve)
After=network-online.target

[Service]
User=freshorama
Environment=API_SERVER_KEY=__SET_AT_DEPLOY_TIME__
Environment=API_SERVER_BRAND_FILE=/etc/freshorama/brand.json
Environment=API_SERVER_HOST=127.0.0.1
Environment=API_SERVER_PORT=8080
WorkingDirectory=/opt/slave-agent
ExecStart=/usr/bin/python3 -m hermes_cli.main serve --host 127.0.0.1 --port 8080 --no-open
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Put the real key in a drop-in (`/etc/systemd/system/freshorama-assistant.service.d/env.conf`,
`EnvironmentFile=` also works) with `chmod 600` — never in the repo, never in
git, never in the brand file.

## 6. Security notes

- Keep the server loopback-only and terminate TLS at your proxy (nginx/Caddy).
- Rotate `API_SERVER_KEY` per environment; treat it like a password.
- The brand file shapes tone and facts; it grants no tools by itself —
  toolsets stay governed by the gateway config (`_get_platform_tools`).
- Open questions for the Freshorama admin team (transport confirmation,
  hosting shape, identity model, secrets channel, staging contact) are
  tracked in admineverywhere issue #18.
