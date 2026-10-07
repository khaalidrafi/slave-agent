"""Tests for the light-core floor checker (scripts/ci/kernel_floor.py).

The checker is the enforcement arm of FORK.org's doctrine, and the import scan is what makes
subsystem removal safe on a machine that cannot launch the fork. Both are pure over injected file
lists, so these tests never touch the real tree -- they assert how the checker relates an import
name to a tracked file, which is the contract that would silently rot if the scan changed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "kernel_floor.py"
_spec = importlib.util.spec_from_file_location("kernel_floor", _SCRIPT)
kf = importlib.util.module_from_spec(_spec)
sys.modules["kernel_floor"] = kf
_spec.loader.exec_module(kf)


def _scan(import_lines: str, tree: list[str]) -> list[kf.DanglingImport]:
    """Run the import scanner over one fake module plus a fake tree of tracked paths."""

    def read(path: str) -> str:
        return import_lines if path == "pkg/holder.py" else ""

    return kf.find_dangling_imports(["pkg/holder.py", *tree], set(tree), read)


def test_dangling_submodule_import_is_reported():
    """A deleted module behind a real package must surface, not fail silently at runtime."""
    findings = _scan("from pkg.gone import thing\n", ["pkg/__init__.py"])
    assert [(f.module, f.kind) for f in findings] == [("pkg.gone", "static")]
    assert "pkg/holder.py:1" in str(findings[0])


def test_import_form_needs_the_whole_dotted_module():
    """`import a.b.c` binds a.b.c, so a missing leaf is a finding even when a.b exists."""
    assert _scan("import pkg.gone\n", ["pkg/__init__.py"]) != []
    assert _scan("import pkg.mod\n", ["pkg/__init__.py", "pkg/mod.py"]) == []


def test_names_imported_out_of_a_module_are_not_paths():
    """`from pkg.mod import thing, other` checks pkg.mod, not thing or other."""
    assert _scan("from pkg.mod import thing, other\n", ["pkg/mod.py"]) == []


def test_existing_package_import_resolves():
    """`from pkg import mod` needs only the package itself."""
    assert _scan("from pkg import mod\n", ["pkg/__init__.py", "pkg/mod.py"]) == []


def test_namespace_package_without_init_resolves():
    """A directory of tracked files is importable even without __init__.py."""
    assert _scan("import ns.sub\n", ["ns/sub.py"]) == []


def test_third_party_and_relative_imports_are_left_alone():
    """Only our own top-level names are resolved; stdlib/vendor/relative are not ours."""
    tree = ["pkg/__init__.py"]
    assert _scan("import litellm\nimport os.path\nfrom . import sibling\nfrom .. import up\n", tree) == []


def test_dynamic_import_of_a_removed_module_is_reported():
    """Plugin loaders and CLI dispatch build dotted names as strings -- a removal hides there too."""
    findings = _scan('importlib.import_module("pkg.gone")\n', ["pkg/__init__.py"])
    assert [(f.module, f.kind) for f in findings] == [("pkg.gone", "dynamic")]


def test_interpolated_dynamic_name_is_not_claimed():
    """A runtime-built module name cannot be resolved statically, so the scanner stays silent."""
    assert _scan('importlib.import_module(f"pkg.{which}")\n', ["pkg/__init__.py"]) == []


def test_own_top_level_is_packages_plus_root_modules_only():
    """Root modules and package dirs are ours; data files and hidden dirs are not."""
    names = ["agent/loop.py", "run_agent.py", "README.md", "pyproject.toml", ".venv/x.py"]
    assert kf.own_top_level(names) == {"agent", "run_agent"}


def test_floor_only_flags_growth_and_never_shrinkage():
    """The ratchet is down-only: removing is free, adding needs a recorded baseline."""
    baseline = {"core_dependencies": 45, "core_python_lines": 1000}
    assert kf.compare({"core_dependencies": 45, "core_python_lines": 900}, baseline) == []
    assert kf.compare({"core_dependencies": 46, "core_python_lines": 1000}, baseline) == [
        "core_dependencies: 45 -> 46 (+1)"
    ]
    # A metric with no baseline yet is not a violation: --record has to run first.
    assert kf.compare({"core_dependencies": 99}, {}) == []


def test_measure_core_counts_core_dirs_and_root_modules():
    """Tests, apps and docs are not the core, so they must not raise the floor."""
    tree = [
        "agent/loop.py",
        "tools/t.py",
        "tests/test_x.py",
        "apps/desktop/main.py",
        "run_agent.py",
        "README.md",
        "gateway/platforms/telegram.py",
        "plugins/kanban/__init__.py",
    ]
    body = {"agent/loop.py": "a\nb\nc\n", "tools/t.py": "x\n", "run_agent.py": "y\nz\n"}
    floor = kf.measure_core(tree, lambda p: body.get(p, ""))
    # agent/, tools/, gateway/ and the root module are core; tests/ and apps/ are not.
    assert floor["core_python_files"] == 4
    assert floor["core_python_lines"] == 6
    assert floor["tool_files"] == 1
    assert floor["gateway_platform_adapters"] == 1
    assert floor["in_tree_plugin_dirs"] == 1
