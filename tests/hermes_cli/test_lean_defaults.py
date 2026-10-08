"""Contracts for this fork's lean config overlay (``hermes_cli/lean_defaults.py``).

Three things must hold, each a relationship between two pieces of data rather than a
snapshot of a number:

1. the fork ships *something* different from upstream, or the overlay is dead weight;
2. an explicit value in the user's file beats the overlay, per knob;
3. ``hermes_compat: true`` puts every overlaid knob back on upstream's value -- the
   backwards-compatibility guarantee, so it is checked knob for knob, never on one sample.

The last test drives the real ``load_config()`` against a temp ``HERMES_HOME``, because the
overlay's whole point is where it sits in the merge order; a unit test of the helper alone
would pass even if nothing called it.
"""

from __future__ import annotations

import copy

import pytest

from hermes_cli.config_defaults import DEFAULT_CONFIG
from hermes_cli.lean_defaults import (
    COMPAT_KEY,
    LEAN_DEFAULTS,
    apply_lean_defaults,
    hermes_compat_enabled,
)


def _at(config, path):
    node = config
    for segment in path:
        node = node[segment]
    return node


def _merge_user(config, user):
    """``config`` with ``user`` layered over it, the way ``load_config`` does it.

The overlay never merges -- it is handed an already-merged config and the user's raw dict,
and consults the second only to decide what not to write. A test that skipped this step
would be asserting a call order the production path does not have."""
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            _merge_user(config[key], value)
        else:
            config[key] = value
    return config


def test_overlay_lowers_a_path_upstream_spells_differently():
    """Every overlaid path must actually differ from ``DEFAULT_CONFIG``.

An entry that matches upstream is a knob the overlay does nothing to: it would widen the
compat surface without leaning anything, and a later upstream change would silently turn it
into a value the fork ships by accident."""
    for path, lean in LEAN_DEFAULTS.items():
        assert _at(DEFAULT_CONFIG, path) != lean, path


def test_no_user_file_yet_means_every_knob_is_lean():
    """The fresh-install case: nothing on disk, so the overlay supplies all of it."""
    config = apply_lean_defaults(copy.deepcopy(DEFAULT_CONFIG), None)
    for path, lean in LEAN_DEFAULTS.items():
        assert _at(config, path) == lean, path


def test_explicit_user_value_beats_the_overlay_per_knob():
    """Naming one knob keeps it; untouched siblings still get the lean value.

Precedence is per leaf, not per section: a user who pinned ``max_bytes`` must not lose the
savings on ``max_lines``, and must not have their whole ``tool_output`` section replaced
either."""
    user = {"tool_output": {"max_bytes": 99_999}}
    config = apply_lean_defaults(_merge_user(copy.deepcopy(DEFAULT_CONFIG), user), user)

    assert _at(config, ("tool_output", "max_bytes")) == 99_999
    assert _at(config, ("tool_output", "max_lines")) == LEAN_DEFAULTS[
        ("tool_output", "max_lines")]


def test_hermes_compat_restores_every_upstream_value():
    """``hermes_compat: true`` reproduces stock Hermes, knob for knob.

The master's requirement turns on this test: the fork may be lighter, but it must be able
to *be* upstream again from settings alone. Iterated over every overlaid path, so a new
knob cannot join the overlay and be left out of the compat story."""
    user = {COMPAT_KEY: True}
    config = apply_lean_defaults(_merge_user(copy.deepcopy(DEFAULT_CONFIG), user), user)
    for path in LEAN_DEFAULTS:
        assert _at(config, path) == _at(DEFAULT_CONFIG, path), path


@pytest.mark.parametrize("raw", [True, "true", "TRUE", "yes", "on", "1", 1])
def test_compat_switch_accepts_the_spellings_a_human_types(raw):
    assert hermes_compat_enabled({COMPAT_KEY: raw}) is True


@pytest.mark.parametrize("raw", [False, "false", "no", "off", "0", 0])
def test_compat_switch_stays_off_when_told_off(raw):
    assert hermes_compat_enabled({COMPAT_KEY: raw}) is False


def test_compat_switch_defaults_off_with_no_key():
    """Absent key is not compat: the overlay is what this fork ships."""
    assert hermes_compat_enabled(None) is False
    assert hermes_compat_enabled({}) is False


def test_malformed_section_is_repaired_not_respected():
    """A scalar where a mapping belongs names no leaf, so the overlay supplies the shape.

``tool_output: 5`` is user error, and the readers already coerce it to ``{}``. Repairing it
to the lean dict is the documented answer; the test exists to make that a visible choice
rather than an accident of the walk."""
    user = {"tool_output": 5}
    config = apply_lean_defaults(_merge_user(copy.deepcopy(DEFAULT_CONFIG), user), user)
    assert isinstance(_at(config, ("tool_output",)), dict)
    assert _at(config, ("tool_output", "max_bytes")) == LEAN_DEFAULTS[
        ("tool_output", "max_bytes")]


def _path_in(config, path):
    """Whether ``config`` itself spells ``path`` -- ancestors included, coerced values not."""
    node = config
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return False
        node = node[segment]
    return True


def test_save_never_writes_an_injected_lean_value(tmp_path, monkeypatch):
    """The overlay must not contaminate config.yaml.

``save_config`` keeps whatever differs from the defaults it is handed, so those defaults
have to include the overlay. Otherwise a value the fork injected is written to disk, reads
back as an explicit user choice, and then outranks ``hermes_compat: true`` forever."""
    from hermes_cli import config as config_module

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text("", encoding="utf-8")

    config_module.save_config(config_module.load_config())
    written = config_module.read_raw_config()
    for path in LEAN_DEFAULTS:
        assert not _path_in(written, path), path

    # A value the user really set still has to survive the same strip pass.
    (home / "config.yaml").write_text("tool_output:\n  max_bytes: 99999\n", encoding="utf-8")
    config_module.save_config(config_module.load_config())
    written = config_module.read_raw_config()
    assert written["tool_output"]["max_bytes"] == 99_999


def test_compat_switch_survives_a_save(tmp_path, monkeypatch):
    """``hermes_compat`` is a custom top-level key, so nothing in the schema defends it.

If the strip pass dropped it, the switch would silently un-switch itself the first time the
dashboard or ``hermes config set`` rewrote the file."""
    from hermes_cli import config as config_module

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text("hermes_compat: true\n", encoding="utf-8")

    config_module.save_config(config_module.load_config())
    assert config_module.read_raw_config().get(COMPAT_KEY) is True

    """Real ``load_config()``, real file: proves the call site, not just the helper.

A/B on one home -- lean values, then the same file plus ``hermes_compat: true`` -- because
a one-sided test would also pass if the overlay ran on every load regardless of the switch.
"""
    from hermes_cli import config as config_module

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    config_file = home / "config.yaml"

    config_file.write_text("tool_output:\n  max_bytes: 99999\n", encoding="utf-8")
    loaded = config_module.load_config()
    assert loaded["tool_output"]["max_bytes"] == 99_999, "the user's own value must survive"
    assert loaded["tool_output"]["max_lines"] == LEAN_DEFAULTS[("tool_output", "max_lines")]

    config_file.write_text(
        "hermes_compat: true\ntool_output:\n  max_bytes: 99999\n", encoding="utf-8")
    stock = config_module.load_config()
    for path in LEAN_DEFAULTS:
        assert _at(stock, path) == _at(DEFAULT_CONFIG, path), path
    assert stock["tool_output"]["max_bytes"] == 99_999, "compat restores defaults, not the user"
