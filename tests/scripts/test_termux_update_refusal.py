"""The installed-package gate distinguishes commit builds from release packages."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli.steward import COMMIT_BUILD_UPDATE_MESSAGE


@pytest.mark.platforms("posix")
def test_validator_child_decodes_utf8_and_preserves_strict_errors(tmp_path, monkeypatch):
    import os
    from scripts.termux.validate_installed import run

    # Force a non-UTF-8 locale fallback without pretending to be a different OS.
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "ascii")
    message = "café 東京\n"
    command = [sys.executable, "-c", f"import os; os.write(1, {message.encode('utf-8')!r})"]
    assert run(command, dict(os.environ), tmp_path).stdout == message
    with pytest.raises(subprocess.CalledProcessError) as failed:
        run([*command[:-1], command[-1] + "; raise SystemExit(7)"], dict(os.environ), tmp_path)
    assert failed.value.returncode == 7 and failed.value.stdout == message
    with pytest.raises(UnicodeDecodeError):
        run([*command[:-1], "import os; os.write(1, bytes([255]))"], dict(os.environ), tmp_path)


@pytest.fixture(params=["bundle", "commit-build"])
def artifact(tmp_path, request):
    root = tmp_path / "app"
    root.mkdir()
    (root / "install-stamp.json").write_text(json.dumps({
        "source": request.param,
        "distribution": "apt-termux",
        "payload": "runtime",
        "updateMechanism": "external",
        "commit": "a" * 40,
        "tag": None if request.param == "commit-build" else "v1.2.3",
    }), encoding="utf-8")
    return root, request.param


@pytest.mark.platforms("posix")
def test_validator_accepts_real_cli_refusal_for_installed_identity(artifact, monkeypatch, capsys):
    from hermes_cli import main
    from scripts.termux.validate_installed import validate_update_refusal

    root, source = artifact
    monkeypatch.setattr(main, "PROJECT_ROOT", root)
    monkeypatch.delenv("HERMES_MANAGED", raising=False)

    # The installed identity is what the CLI itself must speak: a release package names
    # its package manager, a commit build names nobody.
    main.cmd_update(SimpleNamespace())
    output = capsys.readouterr()
    expected = COMMIT_BUILD_UPDATE_MESSAGE if source == "commit-build" else "pkg upgrade hermes-agent"
    assert expected in output.out + output.err
    validate_update_refusal(root, subprocess.CompletedProcess(["hermes", "update"], 0, output.out, output.err))
    marker = "COMMIT_BUILD_UPDATE_REFUSAL_OK" if source == "commit-build" else "APT_UPDATE_REFUSAL_OK"
    assert marker in capsys.readouterr().out


@pytest.mark.platforms("posix")
def test_validator_rejects_wrong_refusal_or_exit_status(artifact):
    from scripts.termux.validate_installed import validate_update_refusal

    root, source = artifact
    expected = COMMIT_BUILD_UPDATE_MESSAGE if source == "commit-build" else "pkg upgrade hermes-agent"
    other = "pkg upgrade hermes-agent" if source == "commit-build" else COMMIT_BUILD_UPDATE_MESSAGE
    # Only the identity's own message at a clean exit passes; a nonzero status (a crash, or
    # a mutation path that grew back) and a foreign steward's text are both failures.
    validate_update_refusal(root, subprocess.CompletedProcess(["hermes", "update"], 0, expected, ""))
    for status, message in ((2, expected), (1, other), (0, other), (0, "unrelated startup failure")):
        result = subprocess.CompletedProcess(["hermes", "update"], status, message, "")
        with pytest.raises(RuntimeError, match="wrong update refusal"):
            validate_update_refusal(root, result)
