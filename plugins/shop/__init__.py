"""shop — the storefront toolset: an agent that can read a real shop.

Four tools in a named ``shop`` toolset, a ``hermes shop`` CLI, and a ``/shop``
slash command, all over one adapter contract. Registered from a plugin so the
core stays narrow (the Footprint Ladder): no ``tools/`` module, no
``_HERMES_CORE_TOOLS`` entry, nothing sent to the model on calls that have no
shop configured.

Enabling it for a chat is config, not code — ``platform_toolsets.telegram``
lists ``shop`` and the messaging gateway folds the toolset in for that
platform's sessions. A profile with no shop configured gets nothing: the probe
below answers False, so the schemas are never built.

Why a plugin and not ``tools/``: ``tools/`` is the foundational waist. A
storefront is one vertical among many — the same code drives an organic-food
shop in Sylhet, a clinic's appointment API, or a print shop's order queue — and
the store-specific facts (paths, parameter names, status vocabulary) live in the
profile's ``config.yaml``, never in a branch here.

    plugins:
      entries:
        shop:
          settings:
            base_url: http://127.0.0.1:8000
            token_env: SHOP_API_TOKEN     # the secret stays in .env, read via secret_scope
            statuses: [pending, confirmed, shipped, delivered, cancelled]
            lookback_days: 21

Everything a tool returns is the store's own JSON, so every number the agent
reads out loud is a number the shop published. See ``adapter.py`` for the money
law and why this plugin has no write path.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from tools.registry import tool_error, tool_result

from .adapter import (
    RestStorefrontAdapter, StorefrontAdapter, StorefrontUnavailable)

logger = logging.getLogger(__name__)

TOOLSET = "shop"

# ``adapter`` is a setting so a non-REST store ships its own class without
# touching this file: "plugins.shop.myshop:MyAdapter" or an import path.
_BUILTIN_ADAPTERS: Dict[str, Callable[[Dict[str, Any], Optional[str]], StorefrontAdapter]] = {
    "rest": lambda settings, token: RestStorefrontAdapter(settings, token=token),
}


# The settings subtree keys this plugin reads. ``ctx.get_config`` resolves
# relative to ``plugins.entries.shop.settings``, so the keys are named here
# rather than a whole-dict read — that list IS the config contract, and a key
# nobody names is a key that does nothing.
_SETTING_KEYS = (
    "base_url", "token_env", "token", "adapter", "statuses", "lookback_days",
    "max_rows", "timeout_seconds", "rows_field", "paths", "filters", "auth",
)


def _settings(ctx) -> Dict[str, Any]:
    """This profile's shop settings, read live.

    Called per tool invocation, never cached on the plugin: one process serves
    several profiles, so a settings dict frozen at load time would answer every
    shop's bot with the first profile's address.
    """
    settings: Dict[str, Any] = {}
    for key in _SETTING_KEYS:
        value = ctx.get_config(key)
        if value is not None:
            settings[key] = value
    return settings


def _token_for(settings: Dict[str, Any]) -> str:
    """The API token, resolved through the profile's secret scope at call time.

    Never ``os.environ``: one process serves many profiles, and the env holds
    the launch profile's value — so a second shop's bot would read the first
    shop's token. ``get_secret`` is the only correct reader here.
    """
    from agent.secret_scope import get_secret

    env_name = str(settings.get("token_env") or "SHOP_API_TOKEN").strip()
    return str(get_secret(env_name) or settings.get("token") or "")


# One adapter per (profile, settings) — see _build_adapter for why a cache is
# the right shape here and why a settings edit cannot be hidden by it.
_ADAPTERS: Dict[tuple, StorefrontAdapter] = {}


def _build_adapter(ctx) -> StorefrontAdapter:
    settings = _settings(ctx)
    which = str(settings.get("adapter") or "rest").strip().lower()
    factory = _BUILTIN_ADAPTERS.get(which)
    if factory is None:
        factory = _import_adapter(which)
    if factory is None:
        raise StorefrontUnavailable(
            f"unknown adapter '{which}'. Built in: {', '.join(sorted(_BUILTIN_ADAPTERS))}; "
            f"or point settings.adapter at your own 'module:Class'.")
    token = _token_for(settings)
    # Keyed on the profile AND on everything a built adapter behaves differently
    # from: the store address, the secret, the paths, the filters. A settings
    # change lands on a new key, so an edit to base_url or statuses takes effect
    # on the next call — nothing is frozen for the life of the process.
    #
    # What the cache holds is one adapter object per profile, and what that buys
    # is the store's answered filter probe (RestStorefrontAdapter.can_filter_-
    # status): without it, one /shop queue turn costs statuses + 2 reads instead
    # of 2, and a shop owner's API is not a free service.
    from hermes_constants import hermes_home_key

    cache_key = (hermes_home_key(), which, json.dumps(
        {k: settings.get(k) for k in _SETTING_KEYS}, sort_keys=True, default=str), token)
    cached = _ADAPTERS.get(cache_key)
    if cached is not None:
        return cached
    adapter = factory(settings, token)
    _ADAPTERS[cache_key] = adapter
    return adapter


def _import_adapter(spec: str):
    """``pkg.mod:Class`` → a factory, for a store that is not plain REST.

    Import failures surface as an unavailable shop rather than a traceback in
    the agent loop: a typo in one profile's config must not break the turn.
    """
    try:
        module_name, _, attr = spec.partition(":")
        import importlib

        module = importlib.import_module(module_name)
        cls = getattr(module, attr)
    except Exception as exc:
        logger.debug("shop: cannot import adapter %r: %s", spec, exc)
        return None
    return lambda settings, token: cls(settings, token=token)


def _available(ctx) -> Callable[[], bool]:
    """The toolset's probe, bound to this plugin's context.

    A closure, not a module-level function: settings and secrets are per-profile
    and must resolve when the probe runs, under the calling session's scope.
    """
    def probe() -> bool:
        settings = _settings(ctx)
        return bool(str(settings.get("base_url") or "").strip()) and bool(_token_for(settings))

    return probe


# -- tools ---------------------------------------------------------------

def _run(ctx, action: Callable[[StorefrontAdapter], Any]) -> str:
    """One call path for every tool: build, act, and map failure to a sentence
    the agent can say. An exception escaping here would reach the tool-result
    layer as a stack trace, which a model turns into an apology that tells the
    customer nothing about what actually went wrong."""
    try:
        adapter = _build_adapter(ctx)
        return tool_result(action(adapter))
    except StorefrontUnavailable as exc:
        return tool_error(str(exc))
    except Exception as exc:
        logger.debug("shop: %s failed", type(exc).__name__, exc_info=True)
        return tool_error(f"shop lookup failed: {type(exc).__name__}: {exc}")


def _int_arg(args: Dict[str, Any], key: str, default: Optional[int]) -> Optional[int]:
    raw = args.get(key)
    if raw in (None, ""):
        return default
    try:
        return max(int(raw), 1)
    except (TypeError, ValueError):
        return default


def _str_arg(args: Dict[str, Any], key: str) -> str:
    return str(args.get(key) or "").strip()


def make_shop_queue_handler(ctx):
    def handle(args: Dict[str, Any], **_kw) -> str:
        limit = _int_arg(args, "limit", 10)
        days = _int_arg(args, "days", None)

        def action(adapter: StorefrontAdapter):
            settings = _settings(ctx)
            statuses = args.get("statuses") or settings.get("statuses") or []
            window = days if days is not None else int(settings.get("lookback_days") or 21)
            board = adapter.queue_board(list(statuses), window, limit)
            board["days"] = window
            return board

        return _run(ctx, action)

    return handle


def make_shop_orders_handler(ctx):
    def handle(args: Dict[str, Any], **_kw) -> str:
        status = _str_arg(args, "status")
        phone = _str_arg(args, "phone")
        if not status and not phone and not _str_arg(args, "days"):
            # With no filter at all the answer is "the newest 25 orders of a
            # shop with thousands", which is never what was asked. Require a
            # handle on the question rather than burn context on a dump.
            return tool_error(
                "say what you want: status (e.g. pending), a customer phone, or days")
        return _run(ctx, lambda adapter: adapter.list_orders(
            status=status or None, phone=phone or None,
            days=_int_arg(args, "days", None), limit=_int_arg(args, "limit", 10)))

    return handle


def make_shop_order_handler(ctx):
    def handle(args: Dict[str, Any], **_kw) -> str:
        ref = _str_arg(args, "ref") or _str_arg(args, "order_id") or _str_arg(args, "number")
        if not ref:
            return tool_error("an order ref (id or number) is required")
        return _run(ctx, lambda adapter: adapter.get_order(ref))

    return handle


def make_shop_catalog_handler(ctx):
    def handle(args: Dict[str, Any], **_kw) -> str:
        name = _str_arg(args, "name")
        query = _str_arg(args, "query") or _str_arg(args, "search")
        category = _str_arg(args, "category")
        limit = _int_arg(args, "limit", 10)
        if name:
            return _run(ctx, lambda adapter: adapter.get_product(name))
        if not query and not category:
            return tool_error("give a query, a category, or a product name")
        return _run(ctx, lambda adapter: {
            "products": adapter.search_products(query=query or None, category=category or None,
                                                limit=limit)})

    return handle


def _schema(name: str, description: str, properties: Dict[str, Any],
           required: tuple = ()) -> Dict[str, Any]:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(required)}}


_INT = {"type": "integer", "description": "How many rows to return"}
_DAYS = {"type": "integer", "description": "Only orders created in the last N days"}

_SCHEMAS = {
    "shop_queue": _schema(
        "shop_queue",
        "Read the shop's order queue: how many orders sit in each status and the oldest "
        "ones waiting for action. Every figure is counted from the shop's own API — read it "
        "aloud, never add to it or average it. ``source`` says whether a count is the API's "
        "total or a tally over the recent page; when it is a page tally, say so.",
        {"statuses": {"type": "array", "items": {"type": "string"},
                      "description": "Statuses to count (defaults to the configured set)"},
         "days": _DAYS, "limit": _INT}),
    "shop_orders": _schema(
        "shop_orders",
        "List orders filtered by status, customer phone number, and/or age, newest first. "
        "Returns the shop's rows verbatim, including each order's own total.",
        {"status": {"type": "string", "description": "One status, e.g. pending"},
         "phone": {"type": "string", "description": "Customer phone; digits only are matched"},
         "days": _DAYS, "limit": _INT}),
    "shop_order": _schema(
        "shop_order",
        "Read one order in full: line items, the shop's own total, address, status and dates. "
        "This is the answer to 'what did they order and how much'.",
        {"ref": {"type": "string", "description": "Order id or number"}}, ("ref",)),
    "shop_catalog": _schema(
        "shop_catalog",
        "Look up the shop's catalog: search products, or read one product by its exact name to "
        "get its current price and availability. Prices come from the shop, never from memory.",
        {"query": {"type": "string", "description": "Free-text search of the catalog"},
         "name": {"type": "string", "description": "Exact product name for a single-item read"},
         "category": {"type": "string", "description": "Category slug or name to narrow by"},
         "limit": _INT}),
}


# Filled by register(); read by the ``hermes shop`` CLI handler.
_CLI_STATE: Dict[str, Any] = {}


def register(ctx) -> None:
    """Register the shop toolset, the CLI verb, and the /shop slash command."""
    # The CLI path is entered by argparse in the same process, with no plugin
    # context handed to the handler — so the live context is stashed here at
    # registration. A human at a terminal and the agent then read through one
    # code path and see byte-identical data.
    _CLI_STATE["ctx"] = ctx
    handlers = {
        "shop_queue": make_shop_queue_handler(ctx),
        "shop_orders": make_shop_orders_handler(ctx),
        "shop_order": make_shop_order_handler(ctx),
        "shop_catalog": make_shop_catalog_handler(ctx),
    }
    for name, handler in handlers.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=_SCHEMAS[name],
                          handler=handler, check_fn=_available(ctx), emoji="🛒")
    ctx.register_cli_command(
        name="shop", help="Read the configured storefront (queue, orders, catalog)",
        setup_fn=_cli_setup(ctx), handler_fn=_cli_handler,
        description=("Operator CLI for the shop toolset: the same reads the agent has, "
                     "printable in a terminal and callable from a scheduled job."))
    ctx.register_command(
        "shop", handler=_slash_command(ctx),
        description="Read the shop: queue | orders <filters> | order <ref> | catalog <query>",
        args_hint="[queue|orders|order|catalog] [argument]")


# -- CLI -----------------------------------------------------------------

def _cli_setup(ctx) -> Callable[[argparse.ArgumentParser], None]:
    def setup(subparser: argparse.ArgumentParser) -> None:
        subs = subparser.add_subparsers(dest="shop_action")

        # One shared --json for every verb: a script or a scheduled job wants the
        # store's rows, not a pretty table, and the fork's rule is that the
        # terminal and the agent read through ONE code path. So the daily call
        # sheet can be `hermes -p <profile> shop orders --json` instead of a
        # second HTTP reader with its own auth bugs.
        def _verb(name: str, help_text: str, *aliases: str) -> argparse.ArgumentParser:
            parser = subs.add_parser(name, aliases=aliases, help=help_text)
            parser.add_argument("--json", action="store_true", dest="as_json",
                                help="print the raw payload instead of the table")
            return parser

        queue = _verb("queue", "Counts per status + oldest waiting", "q")
        orders = _verb("orders", "List orders by status / phone / age", "o")
        one = _verb("order", "One order in full")
        catalog = _verb("catalog", "Search the catalog, or read one product", "c")
        queue.add_argument("--days", type=int, default=None)
        queue.add_argument("--limit", type=int, default=10)
        orders.add_argument("--status", default="")
        orders.add_argument("--phone", default="")
        orders.add_argument("--days", type=int, default=None)
        orders.add_argument("--limit", type=int, default=10)
        one.add_argument("ref")
        catalog.add_argument("query", nargs="?", default="")
        catalog.add_argument("--name", default="")
        catalog.add_argument("--category", default="")
        catalog.add_argument("--limit", type=int, default=10)
        subs.add_parser("health", help="Can the shop be read with this profile's settings?")
        subparser.set_defaults(func=_cli_handler)

    return setup


def _cli_handler(args: argparse.Namespace) -> int:
    """``hermes shop ...`` — renders the same adapter calls as text.

    The plugin context is handed to the CLI path by the loader through a
    process-level slot: ``register(ctx)`` stores it here, so a human at a
    terminal and the agent get byte-identical data from one code path.
    """
    ctx = _CLI_STATE.get("ctx")
    if ctx is None:
        print("shop: the plugin is not loaded in this process; enable it with "
              "'hermes plugins enable shop'.")
        return 2
    action = getattr(args, "shop_action", None)
    if not action:
        print("usage: hermes shop {queue|orders|order|catalog|health}")
        return 2
    payload = json.loads(_dispatch(ctx, action, vars(args)))
    if "error" in payload:
        print(payload["error"])
        return 1
    if getattr(args, "as_json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(_render(action, payload))
    return 0


def _dispatch(ctx, action: str, args: Dict[str, Any]) -> str:
    if action in {"queue", "q"}:
        return make_shop_queue_handler(ctx)(args)
    if action in {"orders", "o"}:
        return make_shop_orders_handler(ctx)(args)
    if action == "order":
        return make_shop_order_handler(ctx)(args)
    if action in {"catalog", "c"}:
        return make_shop_catalog_handler(ctx)(args)
    return _run(ctx, lambda adapter: {"healthy": adapter.health()})


def _render(action: str, payload: Dict[str, Any]) -> str:
    if action in {"health", "healthy"}:
        return "shop: readable." if payload.get("healthy") else "shop: NOT readable."
    if action in {"order"} or payload.get("ref"):
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if action in {"queue", "q"}:
        lines = [f"queue over {payload.get('days')}d, counted from {payload['source']}"]
        for status, count in (payload.get("counts") or {}).items():
            lines.append(f"  {status:<12} {count}")
        waiting = payload.get("waiting") or []
        if waiting:
            lines.append(f"oldest {len(waiting)} waiting:")
            for row in waiting:
                lines.append(f"  #{row.get('ref')}  {row.get('phone')}  "
                             f"{row.get('total')}{row.get('currency') or ''}  {row.get('created_at')}")
        return "\n".join(lines)
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if rows is None:
        rows = payload.get("products") if isinstance(payload, dict) else None
    rows = rows or []
    lines = [f"{len(rows)} rows"]
    for row in rows:
        lines.append(f"  #{row.get('ref') or row.get('id') or row.get('name')}  "
                     f"{row.get('status') or ''}  {row.get('total') or row.get('price') or ''}  "
                     f"{row.get('created_at') or ''}")
    return "\n".join(lines)


_SLASH_ACTIONS: Dict[str, str] = {
    "queue": "queue", "q": "queue", "board": "queue", "today": "queue",
    "orders": "orders", "o": "orders", "list": "orders",
    "order": "order", "one": "order",
    "catalog": "catalog", "c": "catalog", "product": "catalog", "products": "catalog",
    "search": "catalog",
}
_SLASH_ORDER_FLAGS = {"status", "phone", "days", "limit"}


def _slash_command(ctx) -> Callable[[str], str]:
    """``/shop <verb> [args]`` in a chat — the admin group's own command.

    Parses the same verbs as the CLI and returns the same text. A bare status
    word (``/shop pending``) is what a team actually types, so it is answered as
    ``orders --status pending`` rather than as a usage error. Nothing here
    decides what should be *done* about the number: it is read out, and the
    humans in the group act.
    """
    def handle(raw_args: str) -> str:
        tokens = (raw_args or "").split()
        verb = tokens[0].lower() if tokens else "queue"
        rest = tokens[1:]
        action = _SLASH_ACTIONS.get(verb)
        args: Dict[str, Any] = {"limit": 10, "days": None}
        if action is None:
            # Not a verb we know — treat it as a status, which is the question
            # the group is nearly always asking ("pending?", "shipped?").
            action = "orders"
            args["status"] = verb
        args.update(_flag_args(rest, _SLASH_ORDER_FLAGS))
        if action == "order":
            args["ref"] = rest[0].lstrip("#") if rest else ""
        elif action == "catalog":
            args["query"] = " ".join(rest)
        elif action == "queue":
            args["statuses"] = []
        elif not args.get("status") and not args.get("phone"):
            args["status"] = rest[0] if rest and not rest[0].startswith("--") else "pending"
        if action == "orders" and not (args.get("status") or args.get("phone")):
            return ("usage: /shop queue | /shop pending | /shop order 23 | "
                    "/shop catalog mustard honey")
        return _render(action, json.loads(_dispatch(ctx, action, args)))

    return handle


def _flag_args(tokens: List[str], allowed: set) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    index = 0
    while index < len(tokens) - 1:
        if tokens[index].startswith("--"):
            key = tokens[index][2:]
            if key in allowed:
                value = tokens[index + 1]
                out[key] = int(value) if key in {"days", "limit"} else value
                index += 2
                continue
        index += 1
    return out


