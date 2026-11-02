"""Contract test for the ``serve`` OpenAI-compatible surface (TODOS.org board item).

Covers the wire contract any host panel (AdminEverywhere included) embeds
against: ``POST /v1/chat/completions`` in both stream modes plus Bearer auth,
with inference stubbed — no paid model calls, mirroring
``evals/api_delegation_http_probe.py``. The server side is the real handler
(``APIServerAdapter._handle_chat_completions``) over a real aiohttp server.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

FIXTURE_REPLY = "fixture reply"
API_KEY = "fixture-api-key"


@pytest.fixture(autouse=True)
def _isolated_hermes_home(tmp_path, monkeypatch):
    """Keep the adapter away from a developer's real HERMES_HOME."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    (tmp_path / "hermes-home").mkdir(exist_ok=True)


def _build_adapter(tmp_path, extra=None, calls=None):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from hermes_state import SessionDB

    db = SessionDB(db_path=Path(tmp_path) / "state.db")
    adapter = APIServerAdapter(
        PlatformConfig(enabled=True, extra={"key": API_KEY, **(extra or {})}))
    adapter._session_db = db

    def create_agent(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        agent = MagicMock()
        agent.session_id = kwargs.get("session_id")
        agent.session_prompt_tokens = agent.session_completion_tokens = 0
        agent.session_total_tokens = 0

        def run(**turn):
            callback = kwargs.get("stream_delta_callback")
            if callback:
                callback(FIXTURE_REPLY)
            return {
                "final_response": FIXTURE_REPLY,
                "session_id": agent.session_id,
                "messages": [],
                "api_calls": 1,
            }

        agent.run_conversation.side_effect = run
        return agent

    adapter._create_agent = create_agent
    return adapter


def _client(adapter) -> TestClient:
    app = web.Application()
    app.router.add_post("/v1/chat/completions", adapter._handle_chat_completions)
    return TestClient(TestServer(app))


@pytest.mark.asyncio
async def test_chat_completions_non_stream_contract(tmp_path):
    """stream=false -> 200 application/json, OpenAI chat.completion shape."""
    adapter = _build_adapter(tmp_path)
    async with _client(adapter) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"messages": [{"role": "user", "content": "hi"}], "stream": False},
        )
        assert resp.status == 200
        assert resp.content_type == "application/json"
        body = await resp.json()
        assert body["choices"][0]["message"]["content"] == FIXTURE_REPLY
        assert "id" in body
        assert "usage" in body


@pytest.mark.asyncio
async def test_chat_completions_stream_contract(tmp_path):
    """stream=true -> text/event-stream, data: frames, [DONE] sentinel, deltas reassemble."""
    adapter = _build_adapter(tmp_path)
    async with _client(adapter) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
        assert resp.status == 200
        assert resp.content_type == "text/event-stream"
        raw = await resp.text()
        frames = [ln[len("data: "):] for ln in raw.splitlines() if ln.startswith("data: ")]
        assert frames, "no SSE data frames received"
        assert frames[-1] == "[DONE]", "SSE stream must end with the [DONE] sentinel"

        reassembled = ""
        first = True
        for frame in frames[:-1]:
            payload = json.loads(frame)
            choice = payload["choices"][0]
            delta = choice.get("delta", {})
            if first:
                # First chunk carries the role, OpenAI-style.
                assert delta.get("role", "assistant") == "assistant"
                first = False
            reassembled += delta.get("content", "")
        assert FIXTURE_REPLY in reassembled


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-key"}])
async def test_chat_completions_rejects_bad_auth(tmp_path, headers):
    """Missing or wrong Bearer key -> 401, never a 500."""
    adapter = _build_adapter(tmp_path)
    async with _client(adapter) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status == 401


# --- brand/default persona (business deployments, deploy/freshorama) -------


@pytest.mark.asyncio
async def test_brand_default_persona_applied_when_request_has_no_system(tmp_path):
    """No system message + brand file -> agent runs with the compiled persona."""
    brand = tmp_path / "brand.json"
    brand.write_text(json.dumps({
        "name": "Freshorama Assistant",
        "facts": ["Ships from Lagos daily"],
        "never_do": ["give medical advice"],
    }), encoding="utf-8")
    calls: list = []
    adapter = _build_adapter(tmp_path, extra={"brand_file": str(brand)}, calls=calls)
    async with _client(adapter) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status == 200
    assert len(calls) == 1
    prompt = calls[0].get("ephemeral_system_prompt") or ""
    assert "You are Freshorama Assistant." in prompt
    assert "- Ships from Lagos daily" in prompt
    assert "- give medical advice" in prompt


@pytest.mark.asyncio
async def test_request_system_message_overrides_brand(tmp_path):
    """An explicit system message wins over the server-side brand persona."""
    brand = tmp_path / "brand.json"
    brand.write_text(json.dumps({"name": "Freshorama Assistant"}), encoding="utf-8")
    calls: list = []
    adapter = _build_adapter(tmp_path, extra={"brand_file": str(brand)}, calls=calls)
    async with _client(adapter) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"messages": [
                {"role": "system", "content": "You are Kiosk-7."},
                {"role": "user", "content": "hi"},
            ]},
        )
        assert resp.status == 200
    assert calls[0].get("ephemeral_system_prompt") == "You are Kiosk-7."


def test_brand_file_malformed_fails_fast(tmp_path):
    """A broken brand file must refuse to boot the adapter, not half-apply."""
    brand = tmp_path / "brand.json"
    brand.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        _build_adapter(tmp_path, extra={"brand_file": str(brand)})


def test_brand_file_missing_fails_fast(tmp_path):
    with pytest.raises(ValueError, match="brand file not found"):
        _build_adapter(tmp_path, extra={"brand_file": str(tmp_path / "nope.json")})


def test_no_brand_file_means_no_default_prompt(tmp_path):
    """Without a brand file the adapter behavior is unchanged (prompt None)."""
    calls: list = []
    adapter = _build_adapter(tmp_path, calls=calls)
    assert adapter._brand_default_prompt == ""
