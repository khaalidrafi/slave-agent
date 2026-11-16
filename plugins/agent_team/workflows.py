"""Built-in team rosters: the non-coding workflows (Owner order 2026-11-17).

A roster is data, not code: name, mission, roles with one-line briefs. Each
role runs in order and sees the task plus every earlier role's output, which
is what makes a chain a review chain instead of three unrelated drafts.
"""

from __future__ import annotations

from typing import Any, Dict, List

WORKFLOWS: Dict[str, Dict[str, Any]] = {
    "blog-writing": {
        "name": "Blog writing team",
        "mission": "Produce a publish-ready blog post from one task brief.",
        "roles": [
            {"name": "researcher",
             "brief": "Collect the facts the post needs: key claims, sources, dates, "
                      "and the two numbers that make the argument concrete. List gaps "
                      "you cannot fill as OPEN, do not invent them."},
            {"name": "drafter",
             "brief": "Write the post from the research. One idea per paragraph, short "
                      "declarative sentences, no filler. Name the audience in the "
                      "first two sentences."},
            {"name": "editor",
             "brief": "Cut every sentence that could appear unchanged in another "
                      "company's post. Fix structure, order, and the headline. Return "
                      "the edited post in full."},
            {"name": "fact-checker",
             "brief": "Check every claim in the edited post against the research "
                      "output. Mark each claim KEPT, FIXED (with the fix), or OPEN. "
                      "Never approve a claim the research did not support."},
        ],
    },
    "news-reporting": {
        "name": "News reporting team",
        "mission": "Produce a news-media report: what happened, to whom, verified.",
        "roles": [
            {"name": "researcher",
             "brief": "Establish the factual spine: events in order, actors, dates, "
                      "places. Separate witnessed facts from attributed statements. "
                      "Anything unverified is marked OPEN with its source named."},
            {"name": "drafter",
             "brief": "Write the report in news style: the lede answers who/what/when/"
                      "where, body in descending importance, attribution for every "
                      "non-witnessed claim."},
            {"name": "verifier",
             "brief": "Audit the draft against the research spine. Every claim gets "
                      "KEPT, FIXED, or OPEN. A claim with no source is OPEN, full stop."},
            {"name": "editor",
             "brief": "Final pass: length, order, headline, and neutrality of tone. "
                      "Return the finished report in full."},
        ],
    },
}


def resolve_workflow(name: str, settings: Dict[str, Any] | None) -> Dict[str, Any]:
    """A named roster: built-in, or a deployment's own from plugin settings."""
    if settings:
        teams = settings.get("teams") or {}
        if isinstance(teams, dict) and name in teams:
            team = teams[name]
            if isinstance(team, dict) and isinstance(team.get("roles"), list) and team["roles"]:
                return team
            raise ValueError(f"team '{name}' in settings has no roles list")
    if name in WORKFLOWS:
        return WORKFLOWS[name]
    known = sorted(set(WORKFLOWS) | set((settings or {}).get("teams") or {}))
    raise ValueError(f"unknown workflow '{name}'; known: {', '.join(known)}")


def workflow_names(settings: Dict[str, Any] | None) -> List[str]:
    names = set(WORKFLOWS)
    if settings:
        teams = (settings or {}).get("teams") or {}
        if isinstance(teams, dict):
            names |= set(teams)
    return sorted(names)


def role_prompts(team: Dict[str, Any], task: str) -> List[Dict[str, str]]:
    """The per-role prompts: brief, task, and the accumulated outputs."""
    prompts: List[Dict[str, str]] = []
    for role in team["roles"]:
        parts = [
            f"You are the {role['name']} on a team whose mission is: {team.get('mission', '')}",
            f"Your job: {role['brief']}",
            f"The task: {task}",
        ]
        if prompts:
            parts.append("Earlier roles' outputs follow; build on them, do not repeat them.")
        prompts.append({"role_name": role["name"], "prompt": "\n\n".join(parts)})
    return prompts
