"""The ``shop`` toolset: storefront reads, number provenance, and the read-only law.

Two layers, because each catches a different bug:

* **Registration through real discovery** (a temp ``HERMES_HOME`` +
  ``plugins.enabled``) — a plugin that loads but registers nothing, or registers
  into the wrong toolset, is invisible to a unit test of the handler.
* **Handlers against a live local HTTP storefront** — this adapter's whole job is
  URL escaping, query parameters, envelope shapes and auth headers. A mock proves
  none of that; a real socket on localhost proves all of it.

The invariant tests are why the plugin exists: a number the shop did not publish
must never reach the chat, and no request may be anything but a read.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import hermes_yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_TAGS = itertools.count()
TOKEN = "staff-token"

PRODUCTS = [
    {"name": "Mustard Honey 500g", "price": "620.00", "is_available": True, "category": "honey"},
    {"name": "Chia Seeds 250g", "price": "180.00", "is_available": False, "category": "seeds"},
]
# Two pending, one confirmed. ``total`` already includes ``shipping_fee`` (the
# Freshorama shape, shop/models.py:527), so a plugin that added them again would
# overstate every order it quoted — which is the bug this file exists to catch.
ORDERS = [
    {"id": 23, "status": "pending", "phone": "01711223344", "total": "1300.00",
     "shipping_fee": "60.00", "created_at": "2099-01-09T10:00:00+06:00",
     "items": [{"product": "Mustard Honey 500g", "line_total": "1240.00"}]},
    {"id": 21, "status": "pending", "phone": "+880 1711-998877", "total": "360.00",
     "shipping_fee": "60.00", "created_at": "2099-01-01T09:00:00+06:00", "items": []},
    {"id": 20, "status": "confirmed", "phone": "01812345678", "total": "180.00",
     "shipping_fee": "0.00", "created_at": "2099-01-08T19:30:00+06:00", "items": []},
]
# 2099 dates: ``lookback_days`` defaults to 21, and a fixture dated last week
# would age out of the window mid-century and turn a passing test into a flake.


class _Handler(BaseHTTPRequestHandler):
    """A stand-in shop API: DRF-ish envelope, staff token auth, name-keyed products.

    ``ignore_filters`` reproduces the store that answers ``?status=`` with the
    whole collection — the case that turns a page tally into a wrong total.
    """

    ignore_filters = False

    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler dispatch name
        self.server.seen.append({"method": self.command, "path": self.path,
                                 "authorization": self.headers.get("Authorization")})
        if self.headers.get("Authorization") != f"Token {TOKEN}":
            return self._json({"detail": "Authentication credentials were not provided."}, 401)
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path.rstrip("/") + "/"
        if path == "/api/orders/":
            rows = ORDERS
            if not self.ignore_filters:
                # ``?limit=`` is answered the way a paginating API answers it:
                # the slice, with a ``count`` for the WHOLE filtered set. A
                # ``count`` that followed the page would make every
                # ``limit=1`` read look like a one-order backlog.
                if query.get("limit"):
                    rows = rows[:int(query["limit"][0])]
            if not self.ignore_filters and query.get("status"):
                want = query["status"][0].lower()
                rows = [r for r in rows if r["status"] == want]
                return self._json({"count": self._matching(want), "results": rows})
            return self._json({"results": rows})
        if path.startswith("/api/orders/"):
            ref = path.split("/")[3]
            row = next((r for r in ORDERS if str(r["id"]) == ref), None)
            return self._json(row if row else {"detail": "not found"}, 200 if row else 404)
        if path == "/api/products/":
            rows = PRODUCTS
            if query.get("q"):
                needle = query["q"][0].lower()
                rows = [p for p in PRODUCTS if needle in p["name"].lower()]
            return self._json({"results": rows})
        if path.startswith("/api/products/"):
            name = urllib.parse.unquote(path.split("/")[3])
            row = next((p for p in PRODUCTS if p["name"] == name), None)
            return self._json(row if row else {"detail": "not found"}, 200 if row else 404)
        if path == "/health/":
            return self._json({"status": "ok"})
        return self._json({"detail": "not found"}, 404)

    def _matching(self, status: str) -> int:
        """The store's own total for one state, over the whole collection."""
        return sum(1 for row in ORDERS if row["status"] == status)

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def storefront():
    """A live storefront plus its request log, so a test can assert on the wire."""
    server, url = _serve(_Handler)
    yield {"url": url, "seen": server.seen}
    server.shutdown()
    server.server_close()


@pytest.fixture
def drf_settings(storefront):
    return {"base_url": storefront["url"], "token_env": "SHOP_API_TOKEN",
            "statuses": ["pending", "confirmed"]}


class _Ctx:
    """A fake ``PluginContext`` recording registrations, so handlers are invoked
    exactly as the tool dispatcher invokes them — through ``register(ctx)``."""

    def __init__(self, settings=None):
        self.tools = {}
        self.commands = {}
        self.cli = {}
        self.settings = dict(settings or {})

    def register_tool(self, name, toolset, schema, handler, check_fn=None, emoji="", **_kw):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler,
                            "check_fn": check_fn}

    def register_command(self, name, handler, description="", args_hint="", **_kw):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = {"setup": setup_fn, "handler": handler_fn}

    def get_config(self, key, default=None):
        value = self.settings.get(key)
        return default if value is None else value


def _load_plugin(tag="under_test"):
    """Import ``plugins/shop/__init__.py`` the way ``plugins_loader`` does — as a
    package with its own directory on ``__path__`` — because its
    ``from .adapter import ...`` needs that. A bare file import fails on the
    relative import, which would make the test pass by testing nothing.

    Tagged and evicted per call: the plugin's ``register()`` closures are what we
    exercise, and a cached module would hand one test another test's settings.
    """
    module_name = f"hermes_plugins_test_shop_{tag}"
    plugin_dir = REPO_ROOT / "plugins" / "shop"
    spec = importlib.util.spec_from_file_location(
        module_name, plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)])
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(plugin_dir)]  # type: ignore[attr-defined]
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


@pytest.fixture
def shop_ctx(storefront, drf_settings, monkeypatch):
    monkeypatch.setenv("SHOP_API_TOKEN", TOKEN)
    ctx = _Ctx(drf_settings)
    _load_plugin(next(_TAGS)).register(ctx)
    return ctx


def _configured(storefront, settings, monkeypatch, token=TOKEN):
    """Register the plugin against ``settings`` with ``token`` in the secret env."""
    if token is None:
        monkeypatch.delenv("SHOP_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SHOP_API_TOKEN", token)
    ctx = _Ctx(settings)
    _load_plugin(next(_TAGS)).register(ctx)
    return ctx


def _call(ctx, tool, **args):
    """Invoke a registered handler exactly as the tool dispatcher does: args in,
    JSON text back. ``tool`` is not named ``name`` because ``shop_catalog`` takes
    a ``name`` argument of its own and would collide."""
    return json.loads(ctx.tools[tool]["handler"](args))


class TestRegistration:
    def test_four_tools_land_in_a_named_shop_toolset(self, shop_ctx):
        """``shop`` is a NAMED toolset, never ``_HERMES_CORE_TOOLS``: a session
        with no shop must not pay these schemas on every API call."""
        assert set(shop_ctx.tools) == {"shop_queue", "shop_orders", "shop_order", "shop_catalog"}
        assert {t["toolset"] for t in shop_ctx.tools.values()} == {"shop"}

    def test_every_tool_gates_on_the_probe(self, shop_ctx):
        for name, tool in shop_ctx.tools.items():
            assert callable(tool["check_fn"]), name
            assert tool["check_fn"]() is True, name

    def test_probe_is_false_without_a_url_or_a_token(self, storefront, monkeypatch):
        assert _configured(storefront, {"base_url": ""}, monkeypatch).tools["shop_queue"]["check_fn"]() is False
        settings = {"base_url": storefront["url"]}
        assert _configured(storefront, settings, monkeypatch, token=None) \
            .tools["shop_queue"]["check_fn"]() is False
        assert _configured(storefront, settings, monkeypatch).tools["shop_queue"]["check_fn"]() is True

    def test_cli_verb_and_slash_command_register(self, shop_ctx):
        assert "shop" in shop_ctx.cli and "shop" in shop_ctx.commands


class TestReads:
    def test_an_order_row_passes_through_with_no_invented_field(self, shop_ctx):
        """The money law, asserted on the wire: the shop's ``total`` comes back as
        the string the shop wrote, and the plugin adds no computed field."""
        row = _call(shop_ctx, "shop_order", ref="23")
        assert row["total"] == "1300.00"
        assert set(row) <= set(ORDERS[0])

    def test_pending_filter_returns_only_pending(self, shop_ctx):
        payload = _call(shop_ctx, "shop_orders", status="pending")
        assert [r["status"] for r in payload["rows"]] == ["pending", "pending"]
        assert payload["count"] == 2 and payload["filtered_client_side"] == []

    def test_a_phone_is_matched_on_digits(self, shop_ctx):
        """One person is 01711-998877, +8801711998877 and 8801711998877; a match
        that depends on the spelling loses the customer's order."""
        payload = _call(shop_ctx, "shop_orders", phone="8801711998877")
        assert [r["id"] for r in payload["rows"]] == [21]

    def test_queue_counts_carry_their_provenance(self, shop_ctx):
        board = _call(shop_ctx, "shop_queue")
        assert board["counts"] == {"pending": 2, "confirmed": 1}
        assert board["source"] == "api"
        # Oldest first: #21 has sat since the 1st, #23 since the 9th, and the
        # one losing the sale is the call the owner has to make first.
        assert [row["ref"] for row in board["waiting"]] == [21, 23]

    def test_a_page_tally_is_labelled_as_a_tally(self, monkeypatch):
        """A store that ignores ``?status=`` must not be reported as ``api``.

        The bug guarded is the confident wrong one: a tally over one page
        printed as "2 pending" to a shop sitting on two hundred.
        """
        class _Unfiltered(_Handler):
            ignore_filters = True

        server, url = _serve(_Unfiltered)
        try:
            ctx = _configured(server, {"base_url": url, "statuses": ["pending"],
                                       "filters": {"status": None, "limit": None}},
                              monkeypatch)
            board = _call(ctx, "shop_queue")
            assert board["source"] == "page"
            assert board["counts"]["pending"] == 2 and board["counted_over"] == 3
        finally:
            server.shutdown()
            server.server_close()

    def test_config_that_claims_a_status_filter_the_store_ignores_is_caught(self, monkeypatch):
        """The Freshorama shape: config declares ``?status=`` (reasonable — DRF
        stores usually do), the shop's queryset ignores it and publishes a
        ``count`` over the WHOLE collection.

        Trusting the config there tells the owner "3 pending" when the shop has
        two delivered orders and one pending, in the one number the team acts on.
        The adapter probes with an impossible status and falls back to a labelled
        tally, so the wrong number is never even built.
        """
        class _IgnoresStatus(_Handler):
            ignore_filters = True

        server, url = _serve(_IgnoresStatus)
        try:
            ctx = _configured(server, {"base_url": url, "statuses": ["pending"],
                                       "filters": {"status": "status", "limit": None}},
                              monkeypatch)
            board = _call(ctx, "shop_queue")
            assert board["source"] == "page", board
            assert board["counts"]["pending"] == 2
            assert board["counted_over"] == 3
        finally:
            server.shutdown()
            server.server_close()

    def test_product_name_with_spaces_is_escaped(self, shop_ctx, storefront):
        """Products are addressed by NAME (``lookup_field='name'``), so an
        unescaped space is a 404 that reads to the agent as "out of stock"."""
        row = _call(shop_ctx, "shop_catalog", name="Mustard Honey 500g")
        assert row["price"] == "620.00"
        path = [s["path"] for s in storefront["seen"] if "/api/products/" in s["path"]][-1]
        assert "%20" in path

    def test_availability_is_the_shops_own_field(self, shop_ctx):
        rows = _call(shop_ctx, "shop_catalog", query="chia")["products"]
        assert rows and rows[0]["is_available"] is False

    def test_a_dead_store_answers_with_a_sentence(self, monkeypatch):
        ctx = _configured(None, {"base_url": "http://127.0.0.1:1"}, monkeypatch)
        assert "cannot reach the store" in _call(ctx, "shop_queue")["error"]

    def test_a_bad_token_names_the_env_var(self, storefront, monkeypatch):
        ctx = _configured(storefront, {"base_url": storefront["url"]}, monkeypatch, token="wrong")
        assert "SHOP_API_TOKEN" in _call(ctx, "shop_queue")["error"]

    def test_no_filter_at_all_is_refused_not_dumped(self, shop_ctx):
        assert "error" in _call(shop_ctx, "shop_orders")


class TestReadOnly:
    def test_every_request_the_shop_saw_was_a_get(self, shop_ctx, storefront):
        """Read-only by construction, proven on the wire: an order-placing agent
        would push customer PII through a model endpoint and let a hallucinated
        line item become a real COD order."""
        _call(shop_ctx, "shop_queue")
        _call(shop_ctx, "shop_orders", status="pending")
        _call(shop_ctx, "shop_order", ref="23")
        _call(shop_ctx, "shop_catalog", name="Chia Seeds 250g")
        assert storefront["seen"]
        assert {s["method"] for s in storefront["seen"]} == {"GET"}

    def test_the_contract_exposes_no_write_method(self):
        import importlib
        module = importlib.import_module("plugins.shop.adapter")
        verbs = ("create", "update", "delete", "patch", "post", "place", "refund", "cancel")
        for name in dir(module.StorefrontAdapter):
            assert not name.lower().startswith(verbs), name


class TestCli:
    """``hermes shop`` — the same adapter calls a terminal operator and a
    scheduled job run. The call sheet is a cron script, so if the CLI drifted
    from the tools, the shop's nightly numbers and its chat answers would be two
    different readings of one store."""

    def _parser(self, shop_ctx):
        import argparse

        sub = argparse.ArgumentParser(prog="hermes shop")
        shop_ctx.cli["shop"]["setup"](sub)
        return sub

    def test_json_output_is_the_tools_own_payload(self, shop_ctx, storefront):
        """Byte-identical data through both doors, and the money law travels with
        it: the phone comes back exactly as the shop wrote it."""
        import io
        import contextlib

        args = self._parser(shop_ctx).parse_args(["orders", "--status", "pending", "--json"])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = shop_ctx.cli["shop"]["handler"](args)
        assert code == 0
        payload = json.loads(buffer.getvalue())
        assert [row["id"] for row in payload["rows"]] == [23, 21]
        assert payload["rows"][0]["phone"] == "01711223344"
        assert {s["method"] for s in storefront["seen"]} == {"GET"}


class TestSlashCommand:
    def test_a_bare_status_word_is_answered_as_a_filter(self, shop_ctx):
        text = shop_ctx.commands["shop"]("pending")
        assert "23" in text

    def test_queue_verb_prints_the_board(self, shop_ctx):
        text = shop_ctx.commands["shop"]("queue")
        assert "counted from api" in text and "pending" in text

    def test_order_verb_takes_a_number_with_or_without_hash(self, shop_ctx):
        assert "1300.00" in shop_ctx.commands["shop"]("order 23")

    def test_a_verb_that_is_not_a_status_still_answers(self, shop_ctx):
        """An unknown word is read as a status, so a wrong guess costs a short
        empty answer, not a usage lecture in front of the whole group."""
        assert isinstance(shop_ctx.commands["shop"]("nonsense"), str)


class TestDiscovery:
    def test_bundled_plugin_loads_through_real_discovery(self, tmp_path, monkeypatch):
        home = tmp_path / ".hermes"
        home.mkdir()
        monkeypatch.setenv("HERMES_HOME", str(home))
        (home / "config.yaml").write_text(
            hermes_yaml.safe_dump({"plugins": {"enabled": ["shop"]}}), encoding="utf-8")
        from hermes_cli import plugins as pmod

        mgr = pmod.PluginManager()
        mgr.discover_and_load()
        loaded = mgr._plugins.get("shop")
        assert loaded is not None and loaded.enabled, getattr(loaded, "error", "not discovered")
        assert {"shop_queue", "shop_orders", "shop_order", "shop_catalog"} <= set(mgr._plugin_tool_names)
