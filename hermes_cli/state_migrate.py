"""``migrate-state``: the one-shot state-dir move (board: slave_compat row).

The product's state directory carries its own name. When that name changes
(the fork's rename, applied by the generator), an existing installation's
data does not move with it. This verb moves it once, idempotently, and
refuses to destroy anything: a non-empty target with a present legacy dir is
a conflict a human decides, not a flag we quietly override.

The legacy name comes from ``brand.LEGACY_STATE_DIR`` because brand.py is the
one file the rebrand generator never rewrites — a literal legacy name in any
other module would be renamed on the branded branch and point at the NEW
directory, defeating the migration.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any


def cmd_migrate_state(args: Any) -> int:
    import os

    import brand
    from hermes_constants import _get_platform_default_hermes_home

    if os.environ.get("HERMES_HOME", "").strip():
        print("migrate-state: HERMES_HOME is set; migration moves DEFAULT state dirs only.")
        print("unset it (or move the directory it points at) and rerun.")
        return 2

    new_home = _get_platform_default_hermes_home()
    legacy = new_home.parent / brand.LEGACY_STATE_DIR

    if legacy == new_home:
        print(f"state dir already current: {new_home}")
        print("(this build's default and its legacy name are the same word; nothing to move)")
        return 0
    if not legacy.exists():
        if new_home.exists():
            print(f"no legacy state dir found; current: {new_home}")
        else:
            print(f"no state dir at {legacy} and none at {new_home}; nothing to migrate")
        return 0
    if new_home.exists() and any(new_home.iterdir()):
        print(f"conflict: both {legacy} and a non-empty {new_home} exist")
        print("merge them by hand, or move the new one aside, then rerun.")
        return 2

    if args.dry_run:
        print(f"would move {legacy} -> {new_home}")
        return 0

    if new_home.exists():
        new_home.rmdir()  # empty: verified above
    shutil.move(str(legacy), str(new_home))
    print(f"moved {legacy} -> {new_home}")
    return 0
