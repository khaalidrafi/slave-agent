"""A dashboard-spawned ``slave -p <other> ...`` child keeps the launch environment's
launch-only keys (#135200). The named-profile scrub drops every key the root/home ``.env``
names, but a launch-only key is never loaded from ``.env``: the value in ``os.environ`` is the
administrator's, so a planted ``SLAVE_MANAGED_DIR=`` line must not remove it from the child.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize("planted_name", ["SLAVE_MANAGED_DIR", "slave_managed_dir"])
def test_planted_dotenv_line_does_not_strip_launch_managed_dir(tmp_path, monkeypatch, planted_name):
    root = tmp_path / "slave"
    (root / "profiles" / "other").mkdir(parents=True)
    (root / "profiles" / "other" / "config.yaml").write_text("{}\n")
    (root / ".env").write_text(f"{planted_name}={tmp_path}/planted\nFOO_RESIDUE=1\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("SLAVE_HOME", str(root))
    monkeypatch.setenv("SLAVE_MANAGED_DIR", "/etc/org-policy")
    monkeypatch.setenv("FOO_RESIDUE", "1")
    import slave_constants
    monkeypatch.setattr(slave_constants, "_default_slave_root_memo", None)

    from slave_cli.web_server_gateway import _profile_action_environment

    env = _profile_action_environment(["-p", "other", "gateway", "status"])
    assert env["SLAVE_HOME"] == str(root / "profiles" / "other")
    assert env.get("SLAVE_MANAGED_DIR") == "/etc/org-policy"
    assert "FOO_RESIDUE" not in env  # ordinary launch .env residue is still dropped
