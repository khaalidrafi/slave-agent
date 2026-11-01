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


def _build_adapter(tmp_path):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from hermes_state import SessionDB

    db = SessionDB(db_path=Path(tmp_path) / "state.db")
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={"key": API_KEY}))
    adapter._session_db = db

    def create_agent(**kwargs):
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
