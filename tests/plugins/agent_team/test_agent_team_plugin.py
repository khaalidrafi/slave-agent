"""agent_team plugin: roster resolution, the review chain, and the CLI.

The run test uses a fake facade that records every completion, so the test
asserts what a user sees (each role's output feeds the next) without paying a
model call — and a regression that breaks the chain (a role not seeing its
predecessors) fails the assertion, not the budget.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from plugins.agent_team import run_team
from plugins.agent_team.workflows import (WORKFLOWS, resolve_workflow,
                                          role_prompts, workflow_names)


class _FakeLlm:
    def __init__(self):
        self.calls: list[list[dict]] = []

    def complete(self, messages):
        self.calls.append(messages)
        role = f"role{len(self.calls)}"
        return SimpleNamespace(text=f"<{role} output>")


class _FakeCtx:
    def __init__(self, settings=None):
        self.llm = _FakeLlm()
        self._settings = settings or {}

    def get_config(self, key, default=None):
        return self._settings if key == "settings" else default


class TestRosters:
    def test_builtin_workflows_exist_and_are_non_coding(self):
        assert set(WORKFLOWS) == {"blog-writing", "news-reporting"}
        for team in WORKFLOWS.values():
            assert team["roles"], team
            for role in team["roles"]:
                assert role["name"] and role["brief"]

    def test_unknown_workflow_names_what_is_known(self):
        with pytest.raises(ValueError, match="blog-writing"):
            resolve_workflow("nope", None)

    def test_deployment_defined_roster_wins_over_none(self):
        custom = {"mission": "m", "roles": [{"name": "solo", "brief": "b"}]}
        assert resolve_workflow("custom", {"teams": {"custom": custom}}) == custom
        assert "custom" in workflow_names({"teams": {"custom": custom}})


class TestReviewChain:
    def test_every_role_runs_and_sees_its_predecessors(self):
        ctx = _FakeCtx()
        out = json.loads(run_team(ctx, "blog-writing", "write about honey"))

        assert [o["role"] for o in out["outputs"]] == \
            [r["name"] for r in WORKFLOWS["blog-writing"]["roles"]]
        # Role 2's prompt carries role 1's output; role 1's does not.
        first_prompt = ctx.llm.calls[0][0]["content"]
        assert "write about honey" in first_prompt
        assert "<role1 output>" not in first_prompt
        later_prompt = "".join(m["content"] for m in ctx.llm.calls[1])
        assert "<role1 output>" in later_prompt
        # Four roles, four completions — no hidden retries.
        assert len(ctx.llm.calls) == len(out["outputs"]) == 4

    def test_role_prompts_carry_brief_task_and_chain_note(self):
        prompts = role_prompts(WORKFLOWS["news-reporting"], "cover the flood")
        assert "researcher" in prompts[0]["prompt"] and "cover the flood" in prompts[0]["prompt"]
        assert "Earlier roles" in prompts[1]["prompt"]
        assert "Earlier roles" not in prompts[0]["prompt"]
