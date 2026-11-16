"""agent_team — non-coding team workflows (writing, reporting, custom rosters).

Owner order 2026-11-17: "I want agent-team to support non-coding workflows
like writing team for blogs, reporting team for news media etc. Add agent
team feature in slave-agent as well."

Design, in one breath: a team is a REVIEW CHAIN of named roles over one
task. Each role runs through the host's sanctioned model facade (ctx.llm —
fail-closed, plugin-gated), sees the task and every earlier role's output,
and hands its deliverable to the next role. That structure — draft, critique,
verify, with named deliverables — is what multi-pass writing actually needs;
it costs model calls, never processes, so the core stays as light as the
shop plugin leaves it. Rosters are data: built-ins cover blog-writing and
news-reporting; a deployment adds its own under
``plugins.entries.agent_team.settings.teams``.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any, Callable, Dict, List

from tools.registry import tool_error

from .workflows import resolve_workflow, role_prompts, workflow_names

logger = logging.getLogger(__name__)

TOOLSET = "agent_team"

_TEAM_RUN_SCHEMA = {
    "type": "object",
    "description": "Run a team workflow: every role in the roster works the task in "
                   "order, each seeing the earlier roles' outputs. Use for multi-pass "
                   "non-coding work — a blog post, a news report, a custom roster.",
    "properties": {
        "workflow": {"type": "string",
                     "description": "Roster name: blog-writing, news-reporting, or a "
                                    "deployment-defined team"},
        "task": {"type": "string", "description": "What the team must produce, in one brief"},
    },
    "required": ["workflow", "task"],
}

# The CLI path is entered by argparse in the same process with no context
# handed to the handler, so the live context is stashed here at registration
# (the shop plugin's pattern: terminal and agent through one code path).
_CLI_STATE: Dict[str, Any] = {}


def run_team(ctx: Any, workflow: str, task: str) -> str:
    """Walk the roster; return the run record as JSON text."""
    settings = (ctx.get_config("settings") or {}) if hasattr(ctx, "get_config") else {}
    team = resolve_workflow(workflow, settings)
    outputs: List[Dict[str, str]] = []
    for step in role_prompts(team, task):
        messages: List[Dict[str, str]] = [{"role": "user", "content": step["prompt"]}]
        for prior in outputs:
            messages.append({"role": "assistant", "content": prior["output"]})
            messages.append({"role": "user",
                             "content": f"Continue as the next role. Output of {prior['role']} is above."})
        result = ctx.llm.complete(messages)
        text = getattr(result, "text", None)
        if text is None:  # facade result contract differs by host version
            text = str(getattr(result, "content", result))
        outputs.append({"role": step["role_name"], "output": text})
    return json.dumps({"workflow": workflow, "task": task, "outputs": outputs},
                      ensure_ascii=False, indent=2)


def make_team_run_handler(ctx: Any) -> Callable[[Dict[str, Any]], str]:
    def handler(args: Dict[str, Any]) -> str:
        try:
            return run_team(ctx, args["workflow"], args["task"])
        except ValueError as exc:
            return tool_error(str(exc))
        except Exception as exc:  # the facade raises host-specific errors
            logger.exception("team_run failed")
            return tool_error(f"team run failed: {exc}")
    return handler


def register(ctx: Any) -> None:
    _CLI_STATE["ctx"] = ctx
    ctx.register_tool(name="team_run", toolset=TOOLSET, schema=_TEAM_RUN_SCHEMA,
                      handler=make_team_run_handler(ctx), emoji="🧑‍🤝‍🧑")
    ctx.register_cli_command(
        name="team", help="Team workflows: list rosters, run one",
        setup_fn=_cli_setup, handler_fn=_cli_handler,
        description="Operator CLI for team workflows: lists the built-in and "
                    "deployment-defined rosters, and runs one with "
                    "`team run <name> <task>`.")
    ctx.register_command(
        "team", handler=_slash_command(ctx),
        description="Team workflows: list | run <workflow> <task>",
        args_hint="[list|run] [workflow] [task]")


def _cli_setup(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="team_action")
    subs.add_parser("list", help="List rosters and their roles")
    run = subs.add_parser("run", help="Run a workflow end to end")
    run.add_argument("workflow")
    run.add_argument("task")


def _cli_handler(args: argparse.Namespace) -> int:
    ctx = _CLI_STATE.get("ctx")
    settings = (ctx.get_config("settings") or {}) if ctx and hasattr(ctx, "get_config") else {}
    if args.team_action == "run":
        if ctx is None:
            print("team: no plugin context in this process", file=__import__("sys").stderr)
            return 2
        print(run_team(ctx, args.workflow, args.task))
        return 0
    for name in workflow_names(settings):
        try:
            team = resolve_workflow(name, settings)
        except ValueError:
            continue
        print(f"{name} — {team.get('name', '')}")
        for role in team["roles"]:
            print(f"  {role['name']}: {role['brief'][:76]}")
    return 0


def _slash_command(ctx: Any) -> Callable[[str], str]:
    def handler(raw: str) -> str:
        parts = (raw or "").strip().split(None, 2)
        if not parts or parts[0] == "list":
            settings = (ctx.get_config("settings") or {}) if hasattr(ctx, "get_config") else {}
            return "workflows: " + ", ".join(workflow_names(settings)) + "\n/team run <workflow> <task>"
        if parts[0] == "run" and len(parts) >= 3:
            return run_team(ctx, parts[1], " ".join(parts[2:]))
        return "usage: /team list | /team run <workflow> <task>"
    return handler
