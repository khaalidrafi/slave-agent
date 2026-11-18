#!/usr/bin/env python3
"""Re-brand an upstream Hermes checkout into this fork, in idempotent passes.

Why a script instead of a rename commit: this fork tracks upstream ``main`` and we
intend to keep merging it. A one-shot ``sed`` over 135k occurrences would make every
future merge a conflict, so branding is treated as a *build step* that we re-run after
each merge. Run it, ``git diff``, commit; upstream code stays recognisable.

    python3 scripts/rebrand.py --check             # report what is still branded
    python3 scripts/rebrand.py --apply             # both tiers, in place
    python3 scripts/rebrand.py --tier brand --apply
    python3 scripts/rebrand.py --apply --dry-run   # count per file, write nothing
    python3 scripts/rebrand.py --blind             # files no tier can reach (CI gate)
    python3 scripts/rebrand.py --lint              # + hand-typed brand literals

Two tiers, because the two kinds of occurrence have different risks:

  brand     the product NAME as it appears to a human: string literals, docs, configs.
            ``.py`` is scanned with ``tokenize`` and ``.ts/.tsx/.js/.mjs/.cjs`` with a
            quoted-region regex, so only literals change; the prose formats (docs,
            config, ``.html/.css/.svg/.vue``) are rewritten whole-text, which their
            lookaround guards keep away from code-shaped tokens. Safe to re-run.
  identity  the internal vocabulary: ``hermes_cli`` modules, ``HERMES_*`` env vars,
            the ``~/.hermes`` state dir, the ``hermes-agent`` dist name — plus the
            2.8k tracked paths named after them, which are ``git mv``-ed. Whole-text
            rewrite; this is the tier that can break a running install, so it is
            guarded by a keep-list and verified after every run.

Safety model shared by both tiers:
  * every rewritten ``.py`` is re-compiled; a file that compiled before and doesn't
    after is restored and reported rather than left broken.
  * upstream attribution and third-party names never change (see KEEPS).
  * this file, ``brand.py`` and the fork-brand CI are exempt (``SELF_PATHS``): they
    embed the upstream strings we search for, so rewriting them would blind the tool.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import brand  # noqa: E402

P = brand.PRODUCT  # "slave-agent" — same spelling in prose and as the slug
C = brand.CLI      # "slave" — the console command users type

# --- tier 1: brand name in human-visible text -----------------------------------
# Ordered, first-match-wins. Guards live in the lookarounds: a token touching a
# path/identifier separator ( . / _ - @ $ ) is code, not branding, and is left for
# the identity tier, which handles it with different rules.
RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("npm scope",        re.compile(r"@hermes/"), f"@{brand.SLUG}/"),
    ("possessive",       re.compile(r"Hermes'"), f"{P}’"),
    ("agent name",       re.compile(r"Hermes Agent(?!s)"), P),
    ("agent name lc",    re.compile(r"Hermes agent(?!s)"), P),
    ("agent name caps",  re.compile(r"HERMES AGENT"), P.upper()),
    ("bare brand",       re.compile(r"(?<![A-Za-z0-9_./$@-])Hermes(?![A-Za-z0-9_./-])"), P),
    ("bare brand caps",  re.compile(r"(?<![A-Za-z0-9_./$@-])HERMES(?![A-Za-z0-9_./-])"), P.upper()),
    # CLI invocation: `hermes setup`, "run hermes doctor". Requires a following
    # word, so it never eats `hermes_cli`, `~/.hermes`, `$HERMES_HOME` or a URL.
    ("cli command",      re.compile(r"(?<![A-Za-z0-9_./$@-])hermes(?=[ \t]+[a-z][a-z-]{2,})"), C),
]


def rewrite(text: str) -> tuple[str, int]:
    """Apply RULES in order; return (new_text, number of replacements)."""
    n = 0
    for _, pat, repl in RULES:
        text, k = pat.subn(repl, text)
        n += k
    return text, n


# --- tier 2: internal vocabulary -------------------------------------------------
# KEEPS are matched first and returned untouched. Each is a name we do not own:
#   NousResearch/hermes-agent          upstream repo path, any case — our origin
#                                      remote points there; the name is upstream's
#                                      (the updater that read its releases is gone,
#                                      but the remote and the docs keep the path)
#   hermes-agent.nousresearch.com      upstream docs + install one-liner host
#   @hermes.dev                        contributor email domain (contributors/ paths)
#   hermes-parser / hermes-estree      Meta's Hermes JS engine, pulled in transitively
#                                      by package-lock.json — NOT our package
#   nousresearch/hermes-sandbox        upstream's published sandbox image (the default
#                                      in config_defaults pulls it; we build no own)
#   hermes-4 / Hermes-3 / hermes3      upstream's published MODEL IDs (hermes-4-405b,
#                                      Hermes-3-Llama-3.1-70B, openrouter/hermes3:70b):
#                                      a model's name belongs to whoever trained it
KEEP_RE = re.compile(
    r"NousResearch/hermes-agent|nousresearch/hermes-agent|hermes-agent\.nousresearch\.com"
    r"|@hermes\.dev"
    r"|hermes-parser|hermes-estree|hermes-engine"
    r"|nousresearch/hermes-sandbox"
    r"|hermes-?\d|Hermes-?\d"
    # Upstream plugin-catalog schema key: third-party catalog format, renamed
    # keys would corrupt every entry (upstream tooling reads requires_hermes).
    r"|requires_hermes"
    # Third-party and upstream-official plugin repositories: someone else's
    # repo names (Qhantom-Labs/hermesclaw, raw.githubusercontent URLs), never
    # our brand to change.
    r"|github\.com/[\w.-]+/[\w.-]*hermes[\w.-]*"
    r"|githubusercontent\.com/[\w.-]+/[\w.-]*hermes[\w.-]*"
    # Upstream installer host (we ship a package, not an installer).
    r"|hermes-assets\.nousresearch\.com"
    # Upstream container/CI infrastructure paths: /opt/hermes, /etc/hermes,
    # /run/secrets/hermes-env, /home/hermes-check, $RUNNER_TEMP/hermes-*.
    # Facts about upstream's build environments, not user-visible brand.
    r"|(?:/opt|/etc|/run/secrets|/home|/tmp|RUNNER_TEMP)/hermes[\w./-]*"
)
# One alternation, longest/most-specific first, mapped by _identity_sub. The
# standalone arms deliberately allow a leading hyphen (setup-hermes.sh) but not a
# leading . / _ or word char, so dotted paths and identifiers hit the arms above.
IDENTITY_RE = re.compile(
    r"@hermes/|(?P<keep>" + KEEP_RE.pattern + r")"
    r"|hermes-agent(?![\w])|hermes-tui|hermes-ink|hermes-bots"
    r"|HERMES_|hermes_"
    r"|\.hermes(?![\w-])"
    r"|\\hermes(?=[\\/.])"
    r"|hermes(?=[A-Z])"          # camelCase: hermesVersion
    r"|Hermes(?=[A-Za-z0-9_])"   # PascalCase identifiers: HermesCLI
    r"|HERMES(?=[A-Za-z0-9_])"
    r"|-hermes-"
    r"|(?<![\w./@$])hermes(?![\w])"
    r"|(?<![\w./@$])Hermes(?![\w])"
    r"|(?<![\w./@$])HERMES(?![\w])"
)


def _identity_sub(m: re.Match[str]) -> str:
    s = m.group(0)
    if m.lastgroup == "keep" or KEEP_RE.match(s):
        return s
    if s == "@hermes/":
        return f"@{brand.SLUG}/"
    # Everything below is a mechanical case-preserving swap of the token itself.
    return (s.replace("hermes", brand.CLI)
             .replace("Hermes", brand.CLI.capitalize())
             .replace("HERMES", brand.CLI.upper()))


def rewrite_identity(text: str) -> tuple[str, int]:
    """Whole-text identity pass (identifiers, env vars, paths, dist name)."""
    new, n = IDENTITY_RE.subn(_identity_sub, text)
    return new, n


# --- file selection and engines --------------------------------------------------
PROSE_EXTS = {".md", ".markdown", ".txt", ".org", ".yaml", ".yml", ".toml",
              ".po", ".pot", ".json", ".sh", ".bash", ".fish", ".ps1", ".nsi",
              ".nsh", ".service", ".desktop", ".env", ".example", ".cfg", ".ini",
              # Everything below was a silent leak, not a skipped file: an extension
              # absent from these tables is never read, so the old name survives the
              # branded artifact and no ``--check`` reports it. ``rebrand --blind``
              # is the inventory of exactly this, and the fork-brand CI gates on it.
              # Text and config languages — rewritten whole-text, their guards keep
              # the prose rules off code-shaped tokens:
              ".nix", ".mdx", ".xml", ".plist", ".manifest", ".jsonl", ".tmpl",
              ".cmd", ".ahk", ".dockerfile",
              # Web text formats: the dashboard's own stylesheet and index HTML were
              # carrying the product word to the user with no tier able to change it.
              ".html", ".css", ".svg", ".vue"}
CODE_EXTS = {".py": "py", ".ts": "js", ".tsx": "js", ".jsx": "js", ".mjs": "js",
             ".cjs": "js",
             # Plain ``.js`` was absent from the table while being the most common
             # extension in the desktop plugin runtimes — a typo-shaped blind spot.
             ".js": "js",
             # Languages whose user-visible words live in quoted regions: give them the
             # quoted engine, so a bare identifier that happens to read like the brand
             # (a Rust fn name, a C type) is never turned into prose. The identity tier
             # still renames identifiers whole-text, which is what keeps a build honest.
             ".rs": "js", ".mts": "js", ".cts": "js", ".h": "js", ".cs": "js"}
# Plain ``.js`` was absent from the table while being the most common
# extension in the desktop plugin runtimes — a typo-shaped blind spot.
# Files the identity tier alone opens (no prose, so only names/env/paths apply).
IDENTITY_ONLY_EXTS = {".lock", ""}


def covered_extensions() -> set[str]:
    """Every extension at least one tier reads — the CI's blind-spot denominator."""
    return PROSE_EXTS | set(CODE_EXTS) | IDENTITY_ONLY_EXTS
# LICENSE is a legal notice we must not alter; contributors/ is attribution data;
# native/ is vendored. Lockfiles carry our dist name too, so the identity tier
# includes them (they have no prose, so only identity rules could ever apply).
NEVER_RE = re.compile(r"^(LICENSE|contributors/|native/|node_modules/)|(^|/)\.git/")
# Files that embed the *search* vocabulary. Rewriting them would blind or break the
# tooling: rebrand.py holds the rule arms, brand.py the vocabulary, and the
# fork-brand CI asserts that no old import survives.
SELF_PATHS = {"brand.py", "scripts/rebrand.py",
              ".github/workflows/fork-brand-consistency.yml"}

# On top of ``SELF_PATHS``, the only files allowed to type this fork's own vocabulary
# by hand: the sync script that runs the generator, and the fork's document about the
# fork. Everywhere else a branded word is drift — a dev branch keeps upstream's
# vocabulary *on purpose* (FORK.org: you resolve real code, never brand noise), so a
# hand-typed brand is a second spelling no pass regenerates and one more hunk that
# conflicts on the next upstream merge. ``--lint`` is that rule, executable.
BRAND_LITERAL_ALLOW = SELF_PATHS | {"scripts/fork-sync.sh", "FORK.org", "HANDOFF.org",
    # Lead-owned team infra + board/doctrine docs — the repo name appears
    # there on purpose (same doctrine as FORK.org/HANDOFF.org above):
    ".github/workflows/agent-team.yml",
    "agent-team/CHARTER.md", "agent-team/CONTROL.org", "agent-team/MEMBERS.org",
    "agent-team/STATE.org", "agent-team/TODOS.org", "agent-team/CANDIDATES.org",
    "agent-team/CHAT.org",
    "docs/INTEGRATION-ADMINEVERYWHERE.org",
    # The absorbed transcript work tree and the fork-positioned README
    # carry the repo name on purpose (README exists upstream: a future
    # sync resolves its conflicts with ours, per FORK.org):
    "TODOs.org", "README.md",
    # Fork-only surfaces that never exist upstream, so no merge ever sees them:
    # the root contributor guide, the mobile-port contract, the deployment kit,
    # the builder skill, and the spec set. Each names this product because it
    # is ABOUT this product.
    "AGENTS.md", "docs/MOBILE-PORT.org", "deploy/example",
    "skills/slave-agent-builder", "specs/",
    # The 2026-11-17 feature block: the persona package and its CLI, the two
    # plugins, the mobile bootstrap, their tests, and the two new docs — all
    # fork-authored, all naming the product they belong to.
    "persona/", "mobile/", "plugins/agent_team/", "plugins/groupchat/",
    "tests/persona/", "tests/plugins/agent_team/", "tests/plugins/groupchat/",
    "hermes_cli/persona.py", "hermes_cli/state_migrate.py",
    "hermes_cli/subcommands/persona.py", "hermes_cli/subcommands/state_migrate.py",
    "docs/RELEASE.md", "docs/EMACS-ROADMAP-R2-R6.org",
    "agent-team/HR-03-RANKING-DRAFT.org"}


def tracked_files(tier: str) -> list[Path]:
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                             capture_output=True, text=True, check=True).stdout
    paths = []
    for line in listing.splitlines():
        if NEVER_RE.match(line) or line in SELF_PATHS:
            continue
        p = Path(line)
        ext = p.suffix.lower()
        if ext in PROSE_EXTS or ext in CODE_EXTS:
            # tier 1 skips pyproject.toml: its `name`/`[project.scripts]` are the
            # dist's identity and belong to tier 2, not to a prose sweep.
            if not (tier == "brand" and line == "pyproject.toml"):
                paths.append(ROOT / line)
        elif tier == "identity" and ext in {".lock", ""}:
            paths.append(ROOT / line)  # uv.lock, and extension-less launchers/scripts
    return paths


def engine_for(path: Path, tier: str) -> callable:
    """Pick the per-tier rewriter. Identity is whole-text for every file type,
    because module and env names appear outside string literals too."""
    if tier == "identity":
        return rewrite_identity
    kind = CODE_EXTS.get(path.suffix.lower())
    if kind == "py":
        return rewrite_python
    if kind == "js":
        return rewrite_js
    return rewrite


# --- tier 1 literal scanners -----------------------------------------------------
def _split_literal(tok: str) -> tuple[str, str, str] | None:
    """Split a Python string token into (prefix, body, quote) — or None if exotic."""
    m = re.match(r"^([A-Za-z]*)(('''|\"\"\"|'|\"))", tok)
    if not m:
        return None
    prefix, quote = m.group(1), m.group(3)
    if not tok.endswith(quote) or len(tok) < 2 * len(quote):
        return None
    return prefix, tok[m.end():-len(quote)], quote


def _line_offsets(src: str) -> list[int]:
    """Absolute offset of each line start, so token (row, col) -> file offset."""
    offs, acc = [0], 0
    for line in src.splitlines(keepends=True):
        acc += len(line)
        offs.append(acc)
    return offs


def rewrite_python(src: str) -> tuple[str, int]:
    """Rewrite string literals (incl. f-string parts) by offset splice.

    Splicing replaces only the literal regions and leaves every other byte — and
    therefore all indentation, comments and line continuations — untouched. This
    is deliberate: ``tokenize.untokenize`` re-serialises the whole file from token
    types and would reformat code it was never asked to touch.
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable under this interpreter: leave the file alone rather than guess.
        return src, 0
    offs = _line_offsets(src)

    def pos(row_col) -> int:
        row, col = row_col
        return offs[row - 1] + col

    edits, total = [], 0
    for tk in toks:
        if tk.type == tokenize.STRING:
            parts = _split_literal(tk.string)
            if not parts:
                continue
            prefix, body, quote = parts
            if "r" in prefix.lower():  # raw: a \-adjacent word could change meaning
                continue
            new_body, k = rewrite(body)
            if not k:
                continue
            start = pos(tk.start) + len(prefix) + len(quote)
            edits.append((start, start + len(body), new_body))
            total += k
        elif tk.type == tokenize.FSTRING_MIDDLE:  # py>=3.12 tokenises f-strings
            new_body, k = rewrite(tk.string)
            if k:
                edits.append((pos(tk.start), pos(tk.end), new_body))
                total += k
    if not total:
        return src, 0
    out = src
    for start, end, new in sorted(edits, reverse=True):
        out = out[:start] + new + out[end:]
    return out, total


LITERAL_RE = re.compile(r"(['\"`])((?:\\.|(?!\1)[^\\\n])*)\1")


def rewrite_js(src: str) -> tuple[str, int]:
    """Rewrite only single-line quoted regions of a TS/JS/JSON source."""
    total = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal total
        body, k = rewrite(m.group(2))
        total += k
        return f"{m.group(1)}{body}{m.group(1)}"

    return LITERAL_RE.sub(sub, src), total


# --- identity tier: file/dir renames --------------------------------------------
def path_renames() -> list[tuple[str, str]]:
    """Tracked paths whose name carries the old vocabulary, as (old, new) pairs.

    Deepest-first so a child is moved before its parent directory disappears, and
    parent components are transformed by the same rules (tests/hermes_cli/ -> ...).
    """
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                             capture_output=True, text=True, check=True).stdout
    out = []
    for line in listing.splitlines():
        if NEVER_RE.match(line) or "hermes" not in line.lower():
            continue
        new = "/".join(rewrite_identity(c)[0] for c in line.split("/"))
        if new != line:
            out.append((line, new))
    return sorted(out, key=lambda pair: -pair[0].count("/"))


def apply_renames(pairs: list[tuple[str, str]], dry: bool) -> int:
    done = 0
    for old, new in pairs:
        if not (ROOT / old).exists():
            continue  # parent directory move already took this path with it
        target = ROOT / new
        target.parent.mkdir(parents=True, exist_ok=True)
        if not dry:
            subprocess.run(["git", "-C", str(ROOT), "mv", old, new], check=True)
        done += 1
    return done


# --- self-documentation ----------------------------------------------------------
# Each example is what one rule arm is there to catch, so `--mapping` doubles as the
# regression list for the table above: read it, and you know what the fork renames and
# what it deliberately leaves alone.
MAPPING_EXAMPLES = (
    "Hermes Agent prints a banner",          # brand: product name in prose
    "run hermes setup first",                # brand: CLI invocation
    "import { Foo } from '@hermes/shared'",  # brand: npm scope inside a literal
    "Hermes' tool store",                    # brand: possessive
    "hermes_cli/main.py",                    # identity: module + path
    "HERMES_HOME=/tmp/x",                    # identity: env var
    "hermes_state_dbfile.py",                # identity: sibling module
    "get_hermes_home()",                     # identity: function name
    "hermesVersion",                         # identity: camelCase (TS)
    "class HermesCLI:",                      # identity: PascalCase
    "~/.hermes/config.yaml",                 # identity: state dir
    r"%LOCALAPPDATA%\hermes\bin\uv.exe",     # identity: Windows state dir
    "run-in-hermes-env",                     # identity: hyphenated script name
    "setup-hermes.sh",                       # identity: hyphen-suffix script name
    "hermes-agent[cron]",                    # identity: dist name with extra
    "NousResearch/hermes-agent",             # KEEP: upstream repo, updater target
    "https://hermes-agent.nousresearch.com/install.sh",  # KEEP: upstream docs host
    "hermes-parser",                         # KEEP: Meta's JS engine, third party
)


def show_mapping() -> int:
    """Print what each tier does to a representative string."""
    width = max(len(s) for s in MAPPING_EXAMPLES)
    print(f"{'INPUT'.ljust(width)}  | {'tier 1 (brand)'.ljust(width)}  | tier 2 (identity)")
    print("-" * (width * 3 + 6))
    for src in MAPPING_EXAMPLES:
        brand_pass, _ = rewrite(src)
        ident_pass, _ = rewrite_identity(brand_pass)
        mark = "  (=unchanged)" if ident_pass == brand_pass else ""
        print(f"{src.ljust(width)}  | {brand_pass.ljust(width)}  | {ident_pass}{mark}")
    return 0


# --- blind spots -----------------------------------------------------------------
def blindspots() -> list[str]:
    """Tracked text files that carry a brand word in a format no tier opens.

    An extension missing from the tables above does not fail a run and does not show
    up in ``--check``: it silently keeps the old name in the branded artifact. That is
    the failure mode this reports — the dashboard's stylesheet, not a Python literal.
    Binary files are skipped (``-I``): nothing here can rewrite a PNG anyway.
    """
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "grep", "-l", "-I", "-i", "-e", "hermes", "--", "."],
        capture_output=True, text=True).stdout.splitlines()
    covered = covered_extensions()
    found = []
    for rel in listing:
        if NEVER_RE.match(rel) or rel in SELF_PATHS:
            continue
        if Path(rel).suffix.lower() in covered:
            continue
        found.append(rel)
    return found


def report_blindspots() -> int:
    """Print the blind spots; nonzero exit so CI can gate on generator coverage."""
    found = blindspots()
    for rel in found:
        print(f"[rebrand blind] {rel}")
    print(f"[rebrand blind] {len(found)} files carry the word in a format no tier reads")
    return 1 if found else 0


def hand_brands() -> list[str]:
    """Tracked lines that type the branded vocabulary by hand, outside the allow-list.

    Case-sensitive on purpose: the words searched are the *answer* the generator
    produces, so finding one in the working tree means someone wrote the output rather
    than the rule.
    """
    words = [brand.SLUG, brand.MODULE, f"{brand.CLI.upper()}_"]
    argv = ["git", "-C", str(ROOT), "grep", "-n", "-I", "-F"]
    for word in words:
        argv += ["-e", word]
    hits = subprocess.run(argv + ["--", "."], capture_output=True, text=True).stdout
    found = []
    for line in hits.splitlines():
        path = line.partition(":")[0]
        # Prefix-aware: an allow entry may be a file, or a directory with or
        # without its trailing slash (``specs/`` covers every spec).
        if any(path == a or path.startswith(a if a.endswith("/") else a + "/")
               for a in BRAND_LITERAL_ALLOW):
            continue
        found.append(line[:200])
    return found


def report_lint() -> int:
    """The invariants that hold on *every* branch, cheap enough to run per PR."""
    blind, typed = blindspots(), hand_brands()
    deny = denied_names(deny_names_from_env())
    for rel in blind:
        print(f"[rebrand blind] {rel}")
    for line in typed:
        print(f"[rebrand hand-written] {line}")
    for line in deny:
        print(f"[rebrand denied] {line}")
    idle = "" if deny_names_from_env() else f" (deny lane idle: {DENY_ENV} unset)"
    print(f"[rebrand lint] {len(blind)} files no tier reads, "
          f"{len(typed)} hand-typed brand literals, "
          f"{len(deny)} deployment-name hits{idle}")
    return 1 if (blind or typed or deny) else 0


# --- deployment-name deny lane --------------------------------------------------
# A deployment's name is runtime configuration (specs/013 purity law): it must
# never appear in this tree, not even in a docstring or a fixture. The names
# cannot be checked in — a deny list inside the tree would itself carry them —
# so they arrive through the environment, and CI fills that from a secret the
# Owner seals (the App credentials are Contents-only and cannot write it).
DENY_ENV = "BRAND_DENY_NAMES"


def deny_names_from_env() -> list[str]:
    """Deployment slugs from the environment; empty when the lane is idle."""
    return [s for s in re.split(r"[\s,]+", os.environ.get(DENY_ENV, "")) if s]


def denied_names(names: list[str]) -> list[str]:
    """Tracked lines that carry a deployment name, case-insensitively.

    The 2026-11-16 naming-ban order landed with five code surfaces still
    carrying a customer's name in docstrings and fixtures, every one typed by
    hand. This lane is that lesson as structure: the next name fails ``--lint``
    instead of waiting for a sweep.
    """
    found: list[str] = []
    for name in names:
        hits = subprocess.run(
            ["git", "-C", str(ROOT), "grep", "-n", "-I", "-i", "-F", "-e", name, "--", "."],
            capture_output=True, text=True).stdout
        found.extend(f"[denied: {name}] {line[:180]}" for line in hits.splitlines())
    return found


# --- verification ---------------------------------------------------------------
def verify() -> list[str]:
    """Static checks that the identity rename is self-consistent.

    ``import`` resolution is the one that matters: a module renamed on disk but not
    in code (or vice versa) is an ImportError at first launch, and we cannot launch
    yet on this machine. Cheap to prove statically instead.
    """
    problems: list[str] = []
    # Names, not Path objects: the lookups below compare against import strings.
    module_dirs = {p.name for p in ROOT.iterdir()
                   if p.is_dir() and (p / "__init__.py").exists()}
    module_files = {p.stem for p in ROOT.glob("*.py")}
    # Walk the tracked list, not rglob: node_modules holds an order of magnitude more
    # paths than the repo does, and none of it is ours to check.
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                             capture_output=True, text=True, check=True).stdout.split("\0")
    # Modules generated at RUNTIME by slave_cli code (their importers are
    # executed in subprocesses after the module is written to disk):
    # slave_tools is produced by generate_slave_tools_module.
    generated_modules = {"slave_tools"}
    for rel in tracked:
        if not rel.endswith(".py"):
            continue
        path = ROOT / rel
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # The negative lookahead stops "from slave-agent ..." prose (our own
        # product name in a docstring) from being read as an import.
        for m in re.finditer(r"^(?:from|import)\s+(slave[a-z0-9_]*(?!-))", src, re.M):
            name = m.group(1)
            if name in generated_modules:
                continue
            if name not in module_dirs and name not in module_files:
                problems.append(f"{rel}: unresolved import '{name}'")
        for m in re.finditer(r"^(?:from|import)\s+(hermes[a-z0-9_]*(?!-))", src, re.M):
            problems.append(f"{rel}: leftover import '{m.group(1)}'")
    # Anything still carrying the old word is reported per line, minus the KEEPS
    # (upstream URLs and Meta's hermes-parser, which are not our brand).
    residual = subprocess.run(
        ["git", "-C", str(ROOT), "grep", "-in", "hermes", "--", "."],
        capture_output=True, text=True).stdout.splitlines()
    kept = 0
    for line in residual:
        path_part, _, text = line.partition(":")
        if path_part in SELF_PATHS:
            continue
        stripped = KEEP_RE.sub("", text)
        if "hermes" not in stripped.lower():
            kept += 1
            continue
        problems.append(f"residual: {stripped[:120]}")
    print(f"[rebrand verify] {kept} lines kept (upstream/third-party names)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="report remaining branded hits")
    g.add_argument("--apply", action="store_true", help="rewrite files in place")
    g.add_argument("--mapping", action="store_true",
                   help="print the name table (what changes, what is protected) and exit")
    g.add_argument("--blind", action="store_true",
                   help="list tracked files no tier can reach (fails if any) and exit")
    g.add_argument("--lint", action="store_true",
                   help="blind-spot scan + hand-typed brand scan (the per-PR gate)")
    ap.add_argument("--tier", choices=("brand", "identity", "all"), default="all",
                    help="brand = visible name only; identity = + modules/env/paths (default all)")
    ap.add_argument("--dry-run", action="store_true", help="with --apply: count, don't write")
    ap.add_argument("--only", nargs="*", default=None, help="restrict to these path prefixes")
    ap.add_argument("--no-verify", action="store_true", help="skip the post-apply checks")
    args = ap.parse_args()
    if args.mapping:
        return show_mapping()
    if args.blind:
        return report_blindspots()
    if args.lint:
        return report_lint()

    tiers = ("brand", "identity") if args.tier == "all" else (args.tier,)
    failures: list[str] = []
    for tier in tiers:
        changed, hits = 0, 0
        for path in tracked_files(tier):
            rel = str(path.relative_to(ROOT))
            if args.only and not any(rel.startswith(p) for p in args.only):
                continue
            try:
                src = path.read_bytes().decode("utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary
            new, k = engine_for(path, tier)(src)
            if not k:
                continue
            hits += k
            changed += 1
            if args.check or args.dry_run:
                print(f"{k:5d}  {rel}")
                continue
            if path.suffix.lower() == ".py":
                # Only ship a rewrite that keeps the file parseable.
                try:
                    compile(src, rel, "exec")
                except SyntaxError:
                    new = src  # was already unparseable here; keep it byte-identical
                    compile_ok = False
                else:
                    compile_ok = True
                if compile_ok:
                    try:
                        compile(new, rel, "exec")
                    except SyntaxError as exc:
                        failures.append(f"{rel}: {exc}")
                        continue
            path.write_bytes(new.encode("utf-8"))

        label = "check" if args.check else ("dry-run" if args.dry_run else "applied")
        print(f"[rebrand {tier} {label}] {changed} files, {hits} replacements")

        if tier == "identity" and not args.check and not args.only:
            # --only means a partial rewrite, so moving files then would separate a
            # module from its (still un-rewritten) importers. Full runs only.
            pairs = path_renames()
            if args.dry_run:
                for old, new in pairs[:20]:
                    print(f"  mv {old} -> {new}")
            moved = apply_renames(pairs, args.dry_run or args.check)
            print(f"[rebrand paths {label}] {moved} paths")

    if failures:
        for f in failures:
            print(f"  SKIPPED (would not compile): {f}", file=sys.stderr)
    if not args.no_verify and not args.check and not args.dry_run and not args.only:
        # verify() walks every .py in the tree; a partial (--only) run would report
        # half-rewritten state as breakage, so it is a full-run step only.
        problems = verify()
        print(f"[rebrand verify] {len(problems)} problems")
        for p in problems[:40]:
            print(f"  {p}")
        return 1 if (problems or failures) else 0
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
