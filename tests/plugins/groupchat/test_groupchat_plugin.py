"""Group-chat capabilities: the /remind grammar and /recap's honest degrade."""


from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from plugins.groupchat import make_recap_handler, make_remind_handler, parse_schedule


NOW = datetime(2026, 11, 17, 10, 0, 0)


class TestParseSchedule:
    def test_in_form(self):
        cron, reading = parse_schedule("in 30m", now=NOW)
        assert cron == "30 10 17 11 *" and reading.startswith("once at")

    def test_at_form_rolls_to_tomorrow_when_passed(self):
        cron, _ = parse_schedule("at 09:30", now=NOW)
        assert cron == "30 9 * * *"  # daily shape; repeat=1 makes it once, tomorrow

    def test_at_form_today_when_ahead(self):
        cron, _ = parse_schedule("at 23:45", now=NOW)
        assert cron == "45 23 * * *"

    def test_every_forms(self):
        assert parse_schedule("every 5m")[0] == "*/5 * * * *"
        assert parse_schedule("every 2h")[0] == "0 */2 * * *"
        assert parse_schedule("every 3d")[0] == "0 9 */3 * *"

    def test_bad_grammar_names_the_whole_grammar(self):
        with pytest.raises(ValueError, match="in <n>"):
            parse_schedule("someday soon")


class TestRemindHandler:
    def _handler(self, monkeypatch, created):
        import cron.jobs as jobs
        monkeypatch.setattr(jobs, "create_job",
                            lambda **kw: created.append(kw) or {"id": "j1"})
        return make_remind_handler(SimpleNamespace(), now=NOW)

    def test_valid_reminder_creates_a_cron_job(self, monkeypatch):
        created: list = []
        handler = self._handler(monkeypatch, created)
        out = handler("in 45m check the oven")
        assert "check the oven" in out and "reminder set" in out
        assert created and created[0]["schedule"] == "45 10 17 11 *"
        assert created[0]["repeat"] == 1  # one-shot, not a daily haunting
        assert "check the oven" in created[0]["prompt"]

    def test_bad_schedule_teaches_the_grammar(self, monkeypatch):
        created: list = []
        handler = self._handler(monkeypatch, created)
        assert "usage" in handler("later maybe")
        assert not created


class TestRecapHandler:
    def test_without_a_reachable_agent_it_says_so_plainly(self):
        handler = make_recap_handler(SimpleNamespace())
        out = handler("")
        assert "cannot see" in out and "ask me directly" in out.lower()

    def test_with_history_it_summarizes_through_the_facade(self):
        llm = SimpleNamespace(
            complete=lambda msgs: SimpleNamespace(text="SUMMARY"))
        agent = SimpleNamespace(messages=[
            SimpleNamespace(role="user", content="we shipped the shop plugin"),
            SimpleNamespace(role="assistant", content="noted"),
        ])
        ctx = SimpleNamespace(
            llm=llm,
            _manager=SimpleNamespace(_cli_ref=SimpleNamespace(agent=agent)),
        )
        out = make_recap_handler(ctx)("")
        assert out == "SUMMARY"
