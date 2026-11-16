"""Group-chat capabilities: /remind (chat-to-cron) and /recap.

/remind parses a small, explicit schedule grammar — ``in 30m``, ``at 18:00``,
``every 2h`` — and creates a cron job whose prompt is the reminder text.
Natural-language schedule guessing is deliberately out: a reminder that fires
at the wrong time is worse than one that asks the user to restate the spec.

/recap summarizes the conversation through the plugin's model facade when
the live agent is reachable (terminal/CLI mode). On gateway surfaces the
session transcript lives in the state store keyed by a session id this
handler cannot see; it says exactly that instead of pretending.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable, Optional, Tuple

_SCHEDULE_RE = re.compile(
    r"^(?P<kind>in|at|every)\s+"
    r"(?:(?P<n>\d+)\s*(?P<unit>[smhdw])"
    r"|(?P<clock>\d{1,2}:\d{2}))$",
    re.I,
)

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_schedule(text: str, now: Optional[datetime] = None) -> Tuple[str, str]:
    """Return (cron_5field, human_reading) or raise ValueError naming the grammar.

    cron fields: minute hour day month weekday — the 6-field variant with
    seconds is NOT portable across the scheduler backends cron supports.
    """
    m = _SCHEDULE_RE.match((text or "").strip())
    if not m:
        raise ValueError(
            "schedule must be one of: in <n><s|m|h|d|w> | at <HH:MM> | every <n><s|m|h|d|w>")
    now = now or datetime.now()
    kind = m.group("kind").lower()
    if m.group("clock"):
        hh, mm = m.group("clock").split(":")
        fire = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if fire <= now:
            fire += timedelta(days=1)
        # Daily cron shape + repeat=1 (the handler passes it): a pinned
        # day/month would silently fire again next year.
        cron = f"{fire.minute} {fire.hour} * * *"
        return cron, fire.strftime("once at %H:%M")
    n, unit = int(m.group("n")), m.group("unit").lower()
    if kind == "in":
        fire = now + timedelta(seconds=n * _UNIT_SECONDS[unit])
        cron = f"{fire.minute} {fire.hour} {fire.day} {fire.month} *"
        return cron, fire.strftime("once at %H:%M")
    # every: the portability subset — minutes, hours, days
    if unit == "m":
        cron = f"*/{max(n, 1)} * * * *"
    elif unit == "h":
        cron = f"0 */{max(n, 1)} * * *"
    elif unit == "d":
        cron = f"0 9 */{max(n, 1)} * *"
    else:
        raise ValueError("every accepts m, h, or d only (weeks: convert to days)")
    return cron, f"every {n}{unit}"


def make_remind_handler(ctx, now=None) -> Callable[[str], str]:
    def handler(raw: str) -> str:
        # Three fields: <kind> <spec> <text...> — the schedule is two words
        # ("in 30m"), unlike /shop's verb-only prefixes.
        parts = (raw or "").strip().split(None, 2)
        if len(parts) < 3:
            return ("usage: /remind <in 30m|at 18:00|every 2h> <text>\n"
                    "example: /remind in 45m check the oven")
        try:
            cron, reading = parse_schedule(f"{parts[0]} {parts[1]}", now=now)
        except ValueError as exc:
            return f"usage: /remind <in 30m|at 18:00|every 2h> <text> ({exc})"
        text = parts[2]
        once = parts[0].lower() in ("in", "at")
        try:
            from cron.jobs import create_job
            record = create_job(
                prompt=f"Reminder (you were asked in chat): {text}",
                schedule=cron,
                name=f"remind-{datetime.now():%Y%m%d%H%M%S}",
                deliver="local",
                repeat=1 if once else None,
            )
        except Exception as exc:
            return f"/remind: the scheduler refused the job ({exc})"
        return f"reminder set ({reading}, cron '{cron}') — {text}"
    return handler


def make_recap_handler(ctx) -> Callable[[str], str]:
    def handler(raw: str) -> str:
        count = max(min(int(raw) if (raw or "").strip().isdigit() else 20, 200), 1)
        agent = getattr(getattr(ctx, "_manager", None), "_cli_ref", None)
        agent = getattr(agent, "agent", None) if agent is not None else None
        history = getattr(agent, "messages", None) if agent is not None else None
        if not history:
            return ("/recap needs the live conversation, which gateway sessions hold "
                    "in the state store under a session id this command cannot see. "
                    "Ask me directly to recap and I will — the conversation is in my "
                    "context there.")
        transcript = "\n".join(
            f"{getattr(m, 'role', '?')}: {getattr(m, 'content', m)}"
            for m in history[-count:]
            if getattr(m, "content", None)
        ) or "(nothing said yet)"
        result = ctx.llm.complete([
            {"role": "user",
             "content": "Summarize this conversation in at most five bullets, decisions "
                        "first, open questions last:\n\n" + transcript},
        ])
        text = getattr(result, "text", None) or str(getattr(result, "content", result))
        return text
    return handler


def register(ctx) -> None:
    ctx.register_command(
        "remind", handler=make_remind_handler(ctx),
        description="Schedule a reminder: in 30m | at 18:00 | every 2h <text>",
        args_hint="<schedule> <text>")
    ctx.register_command(
        "recap", handler=make_recap_handler(ctx),
        description="Summarize the conversation (last N messages)",
        args_hint="[N]")
