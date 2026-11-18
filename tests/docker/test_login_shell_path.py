"""Login shells in the image keep slave-agent’ own dirs on PATH.

Debian's ``/etc/profile`` resets PATH for every login shell, so without
``/etc/profile.d/hermes.sh`` a ``bash -l`` (``docker exec <c> bash -l``, ssh, the
terminal tool's background ``bash -lic``) lost ``/opt/hermes/bin`` and bare
``slave`` exited 127 (#56634).
"""
from __future__ import annotations

import subprocess


def test_login_shell_resolves_slave_to_the_image_shim(built_image: str) -> None:
    r = subprocess.run(
        ["docker", "run", "--rm", "-u", "slave", "--entrypoint", "bash", built_image,
         "-lc", 'echo "slave=$(command -v slave)"; echo "path=$PATH"'],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert r.returncode == 0, r.stderr
    lines = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    assert lines["slave"] == "/opt/hermes/bin/hermes"
    entries = lines["path"].split(":")
    assert entries.index("/opt/hermes/bin") < entries.index("/opt/hermes/.venv/bin")
    assert entries.count("/opt/hermes/bin") == 1
