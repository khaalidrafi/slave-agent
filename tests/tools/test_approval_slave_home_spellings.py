"""A sed -i of slave-agent’s own config.yaml is gated whichever way the shell spells SLAVE_HOME (#144033).

The home fold knew only the absolute native path. On Windows the default home is
``%LOCALAPPDATA%\\slave``, and the agent's Git Bash terminal writes that file as
``/c/Users/<me>/AppData/Local/slave/config.yaml``, ``~/AppData/Local/slave/config.yaml``,
``$HOME/AppData/Local/slave/config.yaml`` or ``$LOCALAPPDATA/slave/config.yaml``. Every one of
those passed as safe, so an in-place edit there rewrote the approval policy (approvals.mode, yolo,
allowlist) mid-session. Platform-independent: the spellings are folded from the resolved home, and a
custom SLAVE_HOME under the user home reproduces the same gap on any OS.
"""

import pytest

from tools import approval_home_fold
from tools.approval import detect_dangerous_command

_PROFILE = r"C:\Users\tester"


def _is_dangerous(cmd: str) -> bool:
    return bool(detect_dangerous_command(cmd)[0])


@pytest.fixture
def windows_default_home(monkeypatch):
    """The Windows default SLAVE_HOME, reached through the profile the way Git Bash spells it."""
    monkeypatch.setenv("HOME", _PROFILE)
    monkeypatch.setenv("USERPROFILE", _PROFILE)
    monkeypatch.setenv("LOCALAPPDATA", _PROFILE + r"\AppData\Local")
    monkeypatch.setenv("SLAVE_HOME", _PROFILE + r"\AppData\Local\slave")


class TestSpellingsOfTheSlaveHome:
    def test_the_native_and_forward_slash_forms_were_always_gated(self, windows_default_home):
        assert _is_dangerous("sed -i s/a/b/ ~/.slave/config.yaml") is True
        assert _is_dangerous("sed -i s/a/b/ C:/Users/tester/AppData/Local/slave/config.yaml") is True

    @pytest.mark.parametrize("target", [
        "/c/Users/tester/AppData/Local/slave/config.yaml",  # Git Bash drive form
        "/C/Users/tester/AppData/Local/slave/config.yaml",
        "~/AppData/Local/slave/config.yaml",  # home-relative
        "$HOME/AppData/Local/slave/config.yaml",
        "${HOME}/AppData/Local/slave/config.yaml",
        "$LOCALAPPDATA/slave/config.yaml",  # the variable the default is built from
        "${LOCALAPPDATA}/slave/config.yaml",
        "${USERPROFILE}/AppData/Local/slave/config.yaml",
        r"%LOCALAPPDATA%\slave\config.yaml",
    ])
    def test_every_spelling_of_the_windows_default_home_is_gated(self, windows_default_home, target):
        assert _is_dangerous(f"sed -i s/a/b/ {target}") is True

    def test_the_slave_env_file_is_gated_too(self, windows_default_home):
        assert _is_dangerous("sed -i s/a/b/ /c/Users/tester/AppData/Local/slave/.env") is True
        assert _is_dangerous("sed -i s/a/b/ $LOCALAPPDATA/slave/.env") is True

    def test_the_long_in_place_flag_and_perl_are_gated(self, windows_default_home):
        assert _is_dangerous("sed --in-place s/a/b/ ~/AppData/Local/slave/config.yaml") is True
        assert _is_dangerous("perl -pi -e s/a/b/ ${HOME}/AppData/Local/slave/config.yaml") is True

    def test_a_custom_home_under_the_user_home_is_gated_on_any_os(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/tester")
        monkeypatch.setenv("SLAVE_HOME", "/home/tester/slave-data")
        assert _is_dangerous("sed -i s/a/b/ ~/slave-data/config.yaml") is True
        assert _is_dangerous("sed -i s/a/b/ $HOME/slave-data/config.yaml") is True

    @pytest.mark.platforms("windows")
    def test_a_home_spelled_in_another_case_still_folds_on_windows(self, monkeypatch):
        monkeypatch.setenv("HOME", r"c:\users\tester")
        monkeypatch.setenv("SLAVE_HOME", r"C:\Users\tester\AppData\Local\slave")
        assert _is_dangerous("sed -i s/a/b/ ~/AppData/Local/slave/config.yaml") is True


class TestPathBelowCaseFold:
    """``_path_below`` folds case only on a Windows host, so a HOME and SLAVE_HOME that differ
    only in case still nest there. Runs on every lane by stubbing the host fact."""

    @pytest.mark.parametrize(("family", "expected"), [("win32", "AppData/Local/slave"), ("linux", None)])
    def test_case_fold_follows_the_host_os_family(self, monkeypatch, family, expected):
        monkeypatch.setattr(approval_home_fold.facts, "os_family", lambda: family)
        assert approval_home_fold._path_below(r"c:\users\tester", r"C:\Users\tester\AppData\Local\slave") == expected


class TestUnrelatedPathsStaySafe:
    """Folding a spelling must not turn a sibling config.yaml into slave-agent’s own policy file."""

    @pytest.mark.parametrize("target", [
        "/c/Users/tester/projects/app/config.yaml",
        "~/projects/app/config.yaml",
        "$LOCALAPPDATA/other/config.yaml",
        "/c/Users/tester/AppData/Local/hermes2/config.yaml",
    ])
    def test_a_sibling_config_yaml_is_not_flagged_as_slave_policy(self, windows_default_home, target):
        assert _is_dangerous(f"sed -i s/a/b/ {target}") is False

    def test_a_sibling_of_a_custom_home_is_not_flagged(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/tester")
        monkeypatch.setenv("SLAVE_HOME", "/home/tester/slave-data")
        assert _is_dangerous("sed -i s/a/b/ ~/slave-data-old/config.yaml") is False
        assert _is_dangerous("sed -i s/a/b/ $HOME/slave-data-old/config.yaml") is False
