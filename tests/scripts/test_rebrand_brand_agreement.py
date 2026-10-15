"""``brand.py`` and ``scripts/rebrand.py`` must agree, or the brand is fiction.

The fork's design (FORK.org) is that branding is *generated*, never hand-edited:
``brand.py`` states the vocabulary and the rewriter applies it, so an upstream
merge can be re-branded in one commit instead of carrying a rename diff forever.
That only holds while the two files say the same thing about the same tokens.
Each test here is one pair that must stay equal — a snapshot of a name would just
annoy whoever renames us next, so nothing here asserts a spelling on its own.

These are relationship tests, per the project's testing rules: if the generator
starts emitting a different answer for ``HERMES_HOME`` than ``brand.HOME_ENV``
claims, the branded tree would read one variable and the docs another, and users
would lose their state directory. That is worth a red test.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_rebrand():
    """Import the generator as a module (it is a script, not an installed package)."""
    spec = importlib.util.spec_from_file_location("rebrand", REPO_ROOT / "scripts" / "rebrand.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_brand():
    sys.path.insert(0, str(REPO_ROOT))
    import brand

    return brand


def test_home_env_is_the_name_the_identity_tier_emits():
    """The gap this closes: ``brand.HOME_ENV`` carried the product's two words,
    while the identity tier's mechanical ``HERMES_``-prefix swap drops the second
    one — so the file meant to be the source of truth was wrong about its own
    product, and every state variable in the branded tree would disagree with the
    docs that name it."""
    mod, brand = _load_rebrand(), _load_brand()
    rewritten, hits = mod.rewrite_identity("HERMES_HOME")
    assert hits == 1
    assert rewritten == brand.HOME_ENV


def test_the_env_prefix_brand_advertises_matches_the_generators_prefix():
    """Not just HOME: a renamed variable is looked up by string elsewhere, so the
    whole ``HERMES_*`` family has to land on the prefix ``brand`` claims."""
    mod, brand = _load_rebrand(), _load_brand()
    prefix = brand.HOME_ENV.split("_")[0]          # "SLAVE"
    for upstream in ("HERMES_HOME", "HERMES_RUNTIME_DIR", "HERMES_API_KEY"):
        out, hits = mod.rewrite_identity(upstream)
        assert hits == 1, upstream
        assert out.startswith(prefix + "_"), (upstream, out)
    # And the prose tier must not touch variables at all — that is the identity
    # tier's job; a tier that eats both would rewrite a name twice.
    assert mod.rewrite("export HERMES_HOME=$HERMES_HOME")[1] == 0


def test_every_brand_name_is_what_the_generator_produces_for_its_upstream_token():
    """Each vocabulary slot against the token it is the answer for."""
    mod, brand = _load_rebrand(), _load_brand()

    assert mod.rewrite("Hermes Agent")[0] == brand.PRODUCT
    assert mod.rewrite("run hermes setup")[0].split()[1] == brand.CLI
    assert mod.rewrite_identity("hermes-agent")[0] == brand.SLUG
    assert mod.rewrite_identity("hermes_agent")[0] == brand.MODULE


def test_names_we_do_not_own_survive_both_tiers():
    """The KEEPS: the upstream repo (the update/install target), the upstream docs
    host, contributor email addresses, and Meta's Hermes JS parser. Rewriting any
    of them would break an updater, lose MIT attribution, or point at a package
    that does not exist."""
    mod = _load_rebrand()
    for keep in ("NousResearch/hermes-agent", "hermes-agent.nousresearch.com",
                 "@hermes.dev", "hermes-parser", "hermes-estree"):
        assert mod.rewrite(keep)[1] == 0, keep
        out, _ = mod.rewrite_identity(f"see {keep} for details")
        assert keep in out, (keep, out)


def test_the_brand_tier_rewrites_prose_without_eating_identifiers():
    """The prose tier's guards are the reason it is safe to run over source files:
    a token touching ``.``/``_``/``/``/``$``/``@`` is code, not branding, and must
    be left for the identity tier."""
    mod, brand = _load_rebrand(), _load_brand()
    untouched = ["hermes_cli/main.py", "~/.hermes/config.yaml", "$HERMES_HOME",
                 "HERMES_HOME=1", "import hermes_constants", "hermes-agent.nousresearch.com"]
    for sample in untouched:
        assert mod.rewrite(sample)[1] == 0, sample
    # Sentence-initial prose still becomes the product name — spelled from ``brand``,
    # because a test that types the answer is the drift ``rebrand --lint`` exists to catch.
    assert mod.rewrite("Hermes remembers your context")[0].startswith(brand.PRODUCT + " ")


def test_the_generator_opens_every_format_that_ships_a_word_to_a_user():
    """A format missing from the extension tables is not *skipped*, it is invisible.

    The first version of this tool read ``.py``/``.ts``/docs and nothing else, so the
    dashboard's own stylesheet, the Windows installer, the Nix packaging and the Rust
    bootstrap kept the upstream name and no ``--check`` said so — the branded artifact
    shipped the old brand to users through the one channel nobody was watching. This
    test is the pair between the tables and the file types a brand word actually
    reaches a human through; ``rebrand --blind`` finds a new one, this keeps it found.
    """
    mod = _load_rebrand()
    covered = mod.covered_extensions()
    for ext in (".js", ".html", ".css", ".svg", ".vue", ".json", ".nix", ".mdx",
                ".rs", ".mts", ".h", ".cs", ".cmd", ".tmpl", ".dockerfile"):
        assert ext in covered, ext
