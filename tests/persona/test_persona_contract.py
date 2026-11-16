"""The profile contract, tested as acceptance criteria (specs/013).

Criterion by criterion: one-command install that touches nothing outside the
state dir; two fixture personas whose golden renders differ on every surface
with the same code; a secret VALUE rejected by name; the shop settings shape
unchanged. These are behavior tests on purpose — they assert what a deploying
company can observe, not the schema's internals.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from persona import (PersonaError, activate_persona, active_persona,
                     compile_persona, install_persona, list_personas,
                     render_banner, render_help, render_refusal)
from persona.schema import persona_slug, validate_persona


def _migrate(args):
    from hermes_cli import state_migrate
    return state_migrate.cmd_migrate_state(args)


ACME = {
    "identity": {"company": "Acme Corp", "product": "Acme Desk",
                 "assistant": "Dot", "tagline": "Orders tracked, answers plain.",
                 "locale": "en", "timezone": "Asia/Dhaka"},
    "persona": {"tone": ["friendly", "concise"],
                "voice": ["warm", "brief"],
                "facts": ["Ships from the depot daily"],
                "never_do": ["give medical advice"],
                "refusal_style": "plain",
                "escalation_contact": "support@example.com"},
    "vocabulary": {"keep": ["Service Desk"], "banned": ["vendor"]},
    "capabilities": {"shop": {"base_url": "http://127.0.0.1:8001",
                              "token_env": "ACME_SHOP_TOKEN", "adapter": "rest"}},
    "integration": {"surfaces": ["library", "acp"], "banner": True, "pii_redact": True},
    "secrets": {"ACME_SHOP_TOKEN": "the storefront API token"},
}

BETA = {
    "identity": {"company": "Beta Labs", "product": "Beta Board",
                 "assistant": "Quill", "tagline": "News, verified twice.",
                 "locale": "en", "timezone": "UTC"},
    "persona": {"tone": ["formal"],
                "voice": ["precise"],
                "facts": ["Publishes at 06:00 UTC"],
                "never_do": ["speculate on share prices"],
                "refusal_style": "formal",
                "escalation_contact": "desk@beta.example"},
    "vocabulary": {"keep": ["the wire"], "banned": ["exclusive"]},
    "capabilities": {"shop": {"base_url": "http://10.0.0.9:9000",
                              "token_env": "BETA_SHOP_TOKEN", "adapter": "rest"}},
    "integration": {"surfaces": ["acp"], "banner": False, "pii_redact": False},
    "secrets": {"BETA_SHOP_TOKEN": "the storefront API token"},
}


class TestSchema:
    def test_both_fixtures_validate(self):
        assert validate_persona(ACME) == []
        assert validate_persona(BETA) == []

    def test_unknown_top_level_key_is_named(self):
        problems = validate_persona({**ACME, "identityy": {}})
        assert any("identityy" in p for p in problems)

    def test_tone_is_capped_at_three(self):
        bad = json.loads(json.dumps(ACME))
        bad["persona"]["tone"] = ["a", "b", "c", "d"]
        assert any("persona.tone" in p for p in validate_persona(bad))

    def test_secret_value_shape_is_a_violation(self):
        bad = json.loads(json.dumps(ACME))
        bad["secrets"]["LEAKED"] = "sk-abcdefghijklmnopqrst"
        problems = validate_persona(bad)
        assert any("VALUE" in p for p in problems)

    def test_secret_key_must_be_env_shape(self):
        bad = json.loads(json.dumps(ACME))
        bad["secrets"]["lowercase-name"] = "purpose"
        assert any("ENV VAR NAME" in p for p in validate_persona(bad))

    def test_shop_block_is_the_specs_005_shape(self):
        bad = json.loads(json.dumps(ACME))
        bad["capabilities"]["shop"] = {"base_url": 17}
        assert any("capabilities.shop.base_url" in p for p in validate_persona(bad))


class TestGoldenRenders:
    """Criterion 2: two personas, one code commit, every surface differs."""

    def test_banners_differ_and_carry_the_assistant_name(self):
        a, b = render_banner(ACME), render_banner(BETA)
        assert "Dot" in a and "Quill" in b and a != b

    def test_help_headers_differ(self):
        assert render_help(ACME) != render_help(BETA)
        assert "Dot" in render_help(ACME)

    def test_refusals_differ_per_style(self):
        ra, rb = render_refusal(ACME, "delete an order"), render_refusal(BETA, "delete an order")
        assert ra.startswith("I can't") and rb.startswith("I am unable to")
        assert ra != rb

    def test_compiled_personas_carry_the_contract_blocks(self):
        pa = compile_persona(ACME)
        assert "You are Dot." in pa
        assert "- Ships from the depot daily" in pa
        assert "- Service Desk" in pa
        assert "support@example.com" in pa
        assert "Quill" in compile_persona(BETA)


class TestInstallAndActivation:
    def test_install_lands_only_in_the_state_dir(self, tmp_path):
        outside = tmp_path / "checkout"
        outside.mkdir()
        src = outside / "acme.json"
        src.write_text(json.dumps(ACME), encoding="utf-8")
        home = tmp_path / "home"

        target = install_persona(str(src), home)

        assert target.parent == home / "personas"
        assert target.exists()
        assert active_persona(home)["identity"]["assistant"] == "Dot"
        # Criterion 1: nothing outside the state dir changed.
        assert sorted(p.name for p in outside.iterdir()) == ["acme.json"]

    def test_invalid_persona_lands_nothing_and_names_the_field(self, tmp_path):
        src = tmp_path / "broken.json"
        bad = json.loads(json.dumps(ACME))
        bad["secrets"]["LEAKED"] = "sk-abcdefghijklmnopqrst"
        src.write_text(json.dumps(bad), encoding="utf-8")
        home = tmp_path / "home"

        with pytest.raises(PersonaError, match="VALUE"):
            install_persona(str(src), home)
        assert not (home / "personas").exists() or not list((home / "personas").glob("*.json"))

    def test_activate_and_deactivate_roundtrip(self, tmp_path):
        home = tmp_path / "home"
        slug_a = persona_slug(ACME)
        slug_b = persona_slug(BETA)
        install_persona_str = lambda data, h: install_persona(
            _write(tmp_path, data), h, activate=False)
        install_persona_str(ACME, home)
        install_persona_str(BETA, home)

        activate_persona(slug_a, home)
        assert active_persona(home)["identity"]["assistant"] == "Dot"
        activate_persona(slug_b, home)
        assert active_persona(home)["identity"]["assistant"] == "Quill"

        from persona import deactivate
        deactivate(home)
        assert active_persona(home) is None

    def test_list_reports_problems_not_silence(self, tmp_path):
        home = tmp_path / "home"
        good = _write(tmp_path, ACME)
        bad = json.loads(json.dumps(ACME))
        bad["persona"]["tone"] = ["a", "b", "c", "d"]
        badpath = tmp_path / "bad.json"
        badpath.write_text(json.dumps(bad), encoding="utf-8")
        install_persona(str(good), home, activate=False)
        (home / "personas" / "zz-bad.json").write_text(badpath.read_text(), encoding="utf-8")

        rows = {r["slug"]: r for r in list_personas(home)}
        assert any(r["problems"] for r in rows.values())
        assert any(not r["problems"] for r in rows.values())

    def test_two_personas_never_share_a_slug_or_a_token_name(self):
        assert persona_slug(ACME) != persona_slug(BETA)
        assert ACME["capabilities"]["shop"]["token_env"] != BETA["capabilities"]["shop"]["token_env"]


def _write(tmp_path, data) -> Path:
    p = tmp_path / f"{data['identity']['company'].lower().replace(' ', '-')}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class TestCompatKey:
    """slave_compat is canonical, hermes_compat the alias (board row)."""

    def test_both_spellings_enable_the_overlay_off(self):
        from hermes_cli.lean_defaults import COMPAT_KEY, hermes_compat_enabled
        assert COMPAT_KEY == "slave_compat"
        assert hermes_compat_enabled({"hermes_compat": True}) is True
        assert hermes_compat_enabled({"slave_compat": True}) is True
        assert hermes_compat_enabled({"slave_compat": "yes"}) is True
        assert hermes_compat_enabled({}) is False

    def test_an_explicit_canonical_no_beats_a_stale_alias_yes(self):
        # The overlay's own precedence: an explicit value beats both switches.
        # A user who turned compat OFF with the new key keeps it off, even if
        # the old spelling still says on.
        from hermes_cli.lean_defaults import hermes_compat_enabled
        assert hermes_compat_enabled({"slave_compat": False, "hermes_compat": True}) is False


class TestMigrateState:
    def _no_env_home(self, monkeypatch):
        monkeypatch.delenv("HERMES_HOME", raising=False)

    def test_same_name_tree_is_a_clean_noop(self, tmp_path, monkeypatch):
        self._no_env_home(monkeypatch)
        home = tmp_path / ".hermes"
        home.mkdir()
        monkeypatch.setattr("hermes_constants._get_platform_default_hermes_home", lambda: home)
        # On this dev tree default and legacy are the same word: nothing to do.
        rc = _migrate(SimpleNamespace(dry_run=False))
        assert rc == 0 and home.exists()

    def test_legacy_dir_moves_once_and_is_idempotent(self, tmp_path, monkeypatch):
        self._no_env_home(monkeypatch)
        legacy = tmp_path / ".hermes"
        (legacy / "personas").mkdir(parents=True)
        (legacy / "personas" / "x.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr("hermes_constants._get_platform_default_hermes_home",
                            lambda: tmp_path / ".slave")

        rc = _migrate(SimpleNamespace(dry_run=False))
        assert rc == 0
        assert (tmp_path / ".slave" / "personas" / "x.json").exists()
        assert not legacy.exists()
        # Idempotent: a second run finds nothing to move.
        assert _migrate(SimpleNamespace(dry_run=False)) == 0

    def test_a_nonempty_target_is_a_conflict_not_an_override(self, tmp_path, monkeypatch):
        self._no_env_home(monkeypatch)
        legacy = tmp_path / ".hermes"
        legacy.mkdir()
        target = tmp_path / ".slave"
        (target / "nested").mkdir(parents=True)
        monkeypatch.setattr("hermes_constants._get_platform_default_hermes_home", lambda: target)
        assert _migrate(SimpleNamespace(dry_run=False)) == 2
        assert legacy.exists() and target.exists()
