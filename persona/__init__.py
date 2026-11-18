"""Deployment personas: one artifact turns this agent into a company's assistant.

This is the library seam of specs/013 and specs/014 — the surface a panel
host imports (``from persona import load_persona, compile_persona``), the
surface the ``persona`` CLI verb drives, and the surface the serve adapter's
brand layer extends. Three rules hold everywhere:

- One artifact per deployment (identity, persona, vocabulary, capabilities,
  integration, secrets). Secrets are env var NAMES; a value is a violation.
- The product's own mark stays generator-owned (brand.py, FORK.org); the
  deployment identity is runtime config. Two tiers, two laws, no mixing.
- Profiles never inherit each other: every consumer keys its caches by the
  artifact's own settings and tokens (specs/005 req. 3, restated as a law).

State layout: ``<state>/personas/<slug>.json`` plus ``personas/active``
holding the active slug. The state dir's ``profiles/`` tree belongs to
upstream's config profiles and is never touched here.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .render import (compile_persona, persona_nameplate, render_banner,
                     render_help, render_refusal)
from .schema import (PersonaError, persona_slug, require_valid,
                     validate_persona)

__all__ = [
    "PersonaError", "validate_persona", "require_valid", "persona_slug",
    "load_persona", "install_persona", "activate_persona", "active_persona",
    "list_personas", "personas_dir",
    "compile_persona", "render_banner", "render_help", "render_refusal",
    "persona_nameplate", "redact_text",
]

from .redact import redact_text  # noqa: E402  (re-exported seam surface)


def personas_dir(home: Optional[Path] = None) -> Path:
    """``<state>/personas``, created on demand."""
    if home is None:
        from slave_constants import get_slave_home
        home = get_slave_home()
    d = Path(home) / "personas"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_persona(path: Path | str, *, strict: bool = True) -> Dict[str, Any]:
    """Read and validate one artifact file. Raises PersonaError when strict."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PersonaError(f"{path}: no such persona file") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PersonaError(f"{path}: not valid JSON ({exc})") from None
    if strict:
        return require_valid(data)
    return data


def _fetch(source) -> str:
    """A local path (str or Path) or an http(s) URL; data either way."""
    source = str(source)
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as resp:  # noqa: S310 - explicit user-supplied URL
            return resp.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")


def install_persona(source: str, home: Optional[Path] = None,
                    *, activate: bool = True) -> Path:
    """Validate, land, and (by default) activate a persona from path or URL.

    Returns the landed file. Raises PersonaError naming every problem; an
    invalid artifact lands NOTHING (req. 6: no silent default fallback).
    Nothing outside the state dir is written (acceptance criterion 1).
    """
    try:
        raw = _fetch(source)
    except FileNotFoundError:
        raise PersonaError(f"{source}: no such file") from None
    except (OSError, ValueError) as exc:
        raise PersonaError(f"{source}: unreadable ({exc})") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PersonaError(f"{source}: not valid JSON ({exc})") from None
    require_valid(data)

    target_dir = personas_dir(home)
    target = target_dir / f"{persona_slug(data)}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    if activate:
        (target_dir / "active").write_text(target.stem + "\n", encoding="utf-8")
    return target


def list_personas(home: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every landed artifact, with its slug; invalid files are named, not hidden."""
    out: List[Dict[str, Any]] = []
    for path in sorted(personas_dir(home).glob("*.json")):
        problems = validate_persona(load_persona(path, strict=False))
        out.append({"slug": path.stem, "path": str(path), "problems": problems})
    return out


def active_persona(home: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The active artifact, or None. A broken pointer degrades to None, loudly."""
    d = personas_dir(home)
    pointer = d / "active"
    try:
        slug = pointer.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return None
    if not slug:
        return None
    try:
        return load_persona(d / f"{slug}.json")
    except PersonaError:
        import sys
        print(f"[persona] active persona '{slug}' is invalid; falling back to the product default",
              file=sys.stderr)
        return None


def activate_persona(slug: str, home: Optional[Path] = None) -> Path:
    """Point ``personas/active`` at a landed slug."""
    target = personas_dir(home) / f"{slug}.json"
    if not target.exists():
        landed = ", ".join(p.stem for p in sorted(personas_dir(home).glob("*.json"))) or "none"
        raise PersonaError(f"no persona named '{slug}' (landed: {landed})")
    (personas_dir(home) / "active").write_text(slug + "\n", encoding="utf-8")
    return target


def deactivate(home: Optional[Path] = None) -> None:
    """Return to the product's own identity."""
    pointer = personas_dir(home) / "active"
    if pointer.exists():
        pointer.unlink()
