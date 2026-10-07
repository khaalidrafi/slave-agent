#!/usr/bin/env python3
"""Light-core floor: the metric behind the doctrine, plus the deletion safety net.

FORK.org says the core does one thing -- talk to the model, run tools, learn from what it did --
and that anything else merely *useful* is a plugin the user installs. A doctrine with no number
attached is a preference, so this script turns it into two checks a CI job can fail on:

1. ``--floor``  the size of the core, compared with ``scripts/ci/kernel_floor.json``. The floor is
   DOWN-ONLY: a removal may lower it, a new capability may not raise it. Raising a number is a
   deliberate act (``--record``), so it shows up in a diff of that JSON file and a human reviews
   the decision instead of absorbing it silently. This is the same ratchet idea upstream product
   trees use for dependency floors, applied to our core instead of a crate graph.

2. ``--check-imports``  every import of one of OUR OWN modules resolves to a real file or
   package. This is what makes subsystem removal safe here: the fork does not launch on the
   4 GB dev machine, so we cannot catch a dangling import by running the program. We catch it
   statically instead, before the commit. Third-party and stdlib imports are ignored -- only
   names that exist as a tracked package/module at the repo root are checked.

Usage:
    python3 scripts/ci/kernel_floor.py                      # both checks, human-readable
    python3 scripts/ci/kernel_floor.py --record             # rewrite the floor (intentional!)
    python3 scripts/ci/kernel_floor.py --check-imports --json out.json
    python3 scripts/ci/kernel_floor.py --quiet              # exit code only

Exit status: 0 clean; 1 floor rose, or an own-module import dangles.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / "scripts" / "ci" / "kernel_floor.json"

# Directories that ARE the core, per FORK.org. Everything else (apps/, web/, ui-tui/, locales/,
# website/, skills/, plugins/, evals/, tests/) is either an edge surface or not shipped, and is
# reported but not ratcheted -- growth there is the user's install choice, not our schema cost.
CORE_DIRS = ("agent", "tools", "gateway", "cron", "hermes_cli", "hermes_platform", "acp_adapter", "pm")

# Relative imports (`from . import x`) resolve inside a package we already validate by its own
# absolute imports, so a leading dot is skipped rather than parsed.
_FROM_RE = re.compile(r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\b")
_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)")
# Dynamic imports matter as much as static ones for a removal: plugin loaders and the CLI dispatch
# build dotted names as strings, and a deleted module behind one fails only at runtime.
_DYNAMIC_RE = re.compile(
    r"""(?:import_module|__import__|importlib\.import_module)\s*\(\s*[f]?["']([A-Za-z_][\w.]*)["']"""
)


@dataclass(frozen=True)
class DanglingImport:
    """One import of our own code that no longer points at a file."""

    path: str
    line: int
    module: str
    kind: str  # "static" | "dynamic"

    def __str__(self) -> str:  # noqa: D105 - one-line finding format
        return f"{self.path}:{self.line}  {self.kind}  {self.module}"


def tracked_files(suffix: str | None = None) -> list[str]:
    """Repo-relative paths of tracked files, optionally filtered to one suffix.

    ``git ls-files`` beats walking the tree: it honours the checkout (no .venv, no node_modules)
    and does one process instead of thousands of stat calls on a slow disk.
    """
    args = ["git", "ls-files", "-z"]
    if suffix:
        args.append(f"*{suffix}")
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.split("\0") if p)


def own_top_level(names: list[str]) -> set[str]:
    """Top-level importable names of this repo: package dirs plus root-level modules.

    Only valid Python identifiers qualify, so data files (``README.md``) and dotted directories
    never enter the set. A directory counts wholesale: ``tests`` is importable by name even though
    nothing should import it, and a broken ``import tests.foo`` is exactly what we want flagged.
    """
    identifier = re.compile(r"^[A-Za-z_]\w*$")
    tops = {p.split("/", 1)[0] for p in names if "/" in p}
    tops |= {p[: -len(".py")] for p in names if p.endswith(".py") and "/" not in p}
    return {t for t in tops if identifier.match(t)}


def tracked_dirs(exists: set[str]) -> set[str]:
    """Every directory prefix in the tree, so a namespace package counts as resolvable."""
    dirs: set[str] = set()
    for path in exists:
        parts = path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:depth]))
    return dirs


def module_file(dotted: str) -> tuple[str, str]:
    """The two tracked paths that would make ``dotted`` an importable module."""
    stem = dotted.replace(".", "/")
    return f"{stem}.py", f"{stem}/__init__.py"


def resolves(dotted: str, exists: set[str], dirs: set[str]) -> bool:
    """Is ``dotted`` a module, a package, or a directory in the tree?

    The directory arm covers namespace packages (dirs with no ``__init__.py``). It does not weaken
    the deletion check: a removed module or subsystem directory matches none of the three.
    """
    if not dotted:
        return False
    stem = dotted.replace(".", "/")
    return any(candidate in exists for candidate in module_file(dotted)) or stem in dirs


def find_dangling_imports(files: list[str], exists: set[str], read) -> list[DanglingImport]:
    """Scan ``files`` for own-module imports whose target is not in ``exists``.

    Both import forms require the dotted part before ``import`` to be a real module or package:
    ``import a.b.c`` binds that whole module, and ``from a.b.c import name`` reads ``name`` out of
    module ``a.b.c``. Accepting any shorter prefix would let a deleted module pass the check, which
    is exactly the case a removal needs to catch.
    """
    tops = own_top_level(files)
    dirs = tracked_dirs(exists)
    findings: list[DanglingImport] = []
    for path in files:
        if not path.endswith(".py"):
            continue
        for lineno, line in enumerate(read(path).splitlines(), start=1):
            match = _FROM_RE.match(line) or _IMPORT_RE.match(line)
            module, kind = (match.group(1), "static") if match else (None, None)
            if module is None:
                # A f-string name is built at runtime; resolving it here would be fiction.
                dynamic = _DYNAMIC_RE.search(line)
                if not dynamic or "{" in dynamic.group(1):
                    continue
                module, kind = dynamic.group(1), "dynamic"
            if module.split(".")[0] not in tops:
                continue  # stdlib or third-party: not ours to resolve
            if not resolves(module, exists, dirs):
                findings.append(DanglingImport(path, lineno, module, kind))
    return findings


def measure_core(files: list[str], read) -> dict[str, int]:
    """The numbers the floor is made of. Every one is a cost the user pays, not a vanity metric."""
    in_core = [
        p
        for p in files
        if p.endswith(".py")
        and (p.split("/", 1)[0] in CORE_DIRS or ("/" not in p and p != "conftest.py"))
    ]
    adapters = [p for p in files if p.startswith("gateway/platforms/") and p.endswith(".py")]
    tools = [p for p in files if p.startswith("tools/") and p.endswith(".py")]
    plugins = {p.split("/")[1] for p in files if p.startswith("plugins/") and "/" in p[9:]}
    deps = _core_dependency_count()
    return {
        # How many packages must download/build before the agent starts. The Guix-relevant number.
        "core_dependencies": deps,
        "core_python_files": len(in_core),
        "core_python_lines": sum(read(p).count("\n") for p in in_core),
        # Each adapter is upstream churn we re-resolve on every sync.
        "gateway_platform_adapters": len(adapters),
        "tool_files": len(tools),
        "in_tree_plugin_dirs": len(plugins),
    }


def _core_dependency_count() -> int:
    """Length of ``[project].dependencies`` -- the always-installed closure."""
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as handle:
        return len(tomllib.load(handle).get("project", {}).get("dependencies", []))


def compare(floor: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """Names that grew past the baseline. Equal or smaller is green."""
    return [
        f"{key}: {baseline[key]} -> {floor[key]} (+{floor[key] - baseline[key]})"
        for key, value in sorted(floor.items())
        if value > baseline.get(key, value)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="write the current floor as the baseline")
    parser.add_argument("--check-imports", action="store_true", help="scan for dangling own-module imports")
    parser.add_argument("--floor", action="store_true", help="compare the floor with the baseline only")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="restrict the import scan to these repo-relative prefixes (whole tree by default)",
    )
    parser.add_argument("--json", metavar="PATH", help="also write the floor/dangling report as JSON")
    parser.add_argument("--quiet", action="store_true", help="exit code only")
    args = parser.parse_args(argv)

    files = tracked_files()
    exists = set(files)
    cache: dict[str, str] = {}

    def read(path: str) -> str:
        if path not in cache:
            cache[path] = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        return cache[path]

    floor = measure_core(files, read)
    # The scan is the expensive half (it reads every .py), so it runs on demand: always for a
    # plain invocation, on request with --check-imports, never as a side effect of --record.
    want_imports = args.check_imports or not (args.floor or args.record or args.json)
    if want_imports:
        scope = args.paths or [""]
        scanned = [p for p in files if any(p.startswith(prefix) for prefix in scope)]
        dangling = find_dangling_imports(scanned, exists, read)
    else:
        scanned, dangling = [], []
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    grown = compare(floor, baseline) if baseline and not args.record else []

    rc = 0
    if args.record:
        BASELINE.write_text(json.dumps(floor, indent=2, sort_keys=True) + "\n")
        print(f"recorded floor -> {BASELINE.relative_to(ROOT)}")
        return rc

    if not args.quiet:
        print(f"import scan: {len(scanned)} files" if want_imports else "import scan: skipped")
        print("core floor (down-only):")
        for key, value in sorted(floor.items()):
            mark = "" if not baseline else ("" if baseline.get(key) == value else f"  (baseline {baseline.get(key)})")
            print(f"  {key:26s} {value:>8,d}{mark}")
        for growth in grown:
            print(f"GREW  {growth}")
        for finding in dangling:
            print(f"DANGLING  {finding}")
        if not grown and not dangling and baseline:
            print("floor and imports: clean")
    rc = 1 if grown or dangling else 0
    if args.json:
        Path(args.json).write_text(json.dumps({"floor": floor, "dangling": [str(d) for d in dangling]}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
