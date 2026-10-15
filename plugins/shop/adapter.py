"""Storefront adapter contract and the generic REST implementation.

``plugins/shop`` is a CONTRACT, not a shop. Nothing in this file knows a
product name, a status string, or a URL path that belongs to one particular
store — base URL, per-resource paths, auth style and query-parameter names all
come from the profile's ``config.yaml``. A storefront that is not plain REST
(GraphQL, a vendor SDK, a spreadsheet) ships its own :class:`StorefrontAdapter`
subclass and returns the same rows; the tools, the ``shop`` toolset and the CLI
do not change.

The money law, enforced structurally (this fork's business rule, and the reason
no e-commerce bot on the market can be trusted with a figure):

* **A number the API did not say never leaves this plugin.** No price is added,
  averaged, discounted or rounded here — the rows pass through with the
  serializer's own fields. The model repeats them; it never derives them.
* **The only arithmetic is counting rows**, because "how many orders are
  waiting" is the one question an admin group asks constantly and answering it
  by eyeballing a list is how a model invents a total. When the count is a
  client-side tally over a capped window instead of the API's own ``count``,
  the result says so in ``counted_over`` — a number without its provenance is
  the bug this whole plugin exists to avoid.
* **Read-only.** ``StorefrontAdapter`` has no write method on purpose. An
  order-placing agent would need customer PII to travel through a model
  endpoint, and this fork's rule is that the shop's own checkout does that
  job. Revisit only with an approve-before-send gate (PLAN.org F4).

Stdlib only: the profile runs on whatever interpreter booted the agent, and a
persona bundle must not add a dependency to it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MAX_ROWS = 25
DEFAULT_LOOKBACK_DAYS = 21
# A status string no shop on earth stores, used once per adapter to find out
# whether ``?status=`` actually filters (see RestStorefrontAdapter.can_filter_status).
_UNPROBABLE_STATUS = "__no_such_order_status__"

# Where a REST store keeps its resources, if it keeps them anywhere conventional.
# Every one is overridable in config, because "conventional" is a vendor's opinion.
DEFAULT_PATHS = {
    "orders": "/api/orders/",
    "order": "/api/orders/{ref}/",
    "products": "/api/products/",
    "product": "/api/products/{name}/",
    "health": "/health/",
}
# Which query parameter each filter rides on. A null value means "this store
# cannot filter server-side", which the callers must know because it changes a
# count from an API fact into a tally over a window.
DEFAULT_FILTERS = {
    "status": "status",
    "phone": "phone",
    "search": "q",
    "category": "category",
    "limit": "limit",
    "days": None,
}
# Payload shapes a list endpoint answers with. Checked in order; the first
# present key wins. DRF paginates under ``results``, most hand-written views
# use ``data``/``items``/``list``, and plain serializers return a bare list.
_ROWS_KEYS = ("results", "items", "data", "list", "orders", "products")


class StorefrontUnavailable(Exception):
    """The store could not be read.

    The kind of failure is in the message, because the agent's honest sentence
    differs per kind: "the shop's server is down" vs "I am not allowed to look"
    vs "you have not configured the address". A single generic error would make
    the agent guess, and a guessing agent apologises for the wrong thing.
    """


def _settings_entry(settings: Dict[str, Any], key: str, default: Dict[str, Any]) -> Dict[str, Any]:
    """One dict-of-dicts setting merged over its defaults, tolerating a partial
    author-written block (a user who configures only ``paths.product`` must not
    lose the other four)."""
    raw = settings.get(key)
    merged = dict(default)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if v is not None or k in default})
    return merged


def _extract_rows(payload: Any, rows_field: Optional[str]) -> List[dict]:
    """Normalise a list endpoint's body into rows, whatever envelope it uses."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        raise StorefrontUnavailable("store answered with a body I could not read as a list of rows")
    keys = (rows_field,) if rows_field else _ROWS_KEYS
    for key in keys:
        value = payload.get(key) if isinstance(key, str) else None
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
    return []


def _api_count(payload: Any) -> Optional[int]:
    """The store's own total for this query, when it publishes one.

    Returns ``None`` rather than the length of the page, so a caller can tell
    "the API counted everything" apart from "I only got a page".
    """
    if not isinstance(payload, dict):
        return None
    for key in ("count", "total", "totalCount", "total_count"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


class StorefrontAdapter(ABC):
    """The read contract a storefront must satisfy for the ``shop`` toolset.

    Subclass this and point ``plugins.entries.shop.settings.adapter`` at it (as
    ``module:Class``) to drive a store that is not a plain REST API. Rows are
    returned as-is from the store's serializers; projection, filtering and
    ranking belong to the caller, and arithmetic belongs to nobody.
    """

    name: str = "abstract"

    # Answers the counting path needs, expressed as data an adapter declares:
    # how big a page it will honestly return, and whether it claims a server-side
    # status filter. The claim is checked, never believed — see can_filter_status.
    page_size: int = DEFAULT_MAX_ROWS
    declares_status_filter: bool = False

    def can_filter_status(self) -> bool:
        """Does a status filter actually narrow this store's collection?

        The default trusts the declaration; a REST store overrides it with a
        proof, because a shop API that accepts ``?status=`` and ignores it makes
        the store's own ``count`` describe EVERY order while the board is
        reporting one state — a wrong backlog number, printed as an authoritative
        one. Money law says we would rather count a page and label it.
        """
        return self.declares_status_filter

    @abstractmethod
    def health(self) -> bool:
        """Reachable and authorized? One cheap call, used by the setup proof."""

    @abstractmethod
    def list_orders(
        self, *, status: Optional[str] = None, phone: Optional[str] = None,
        days: Optional[int] = None, limit: int = DEFAULT_MAX_ROWS,
    ) -> Dict[str, Any]:
        """Order rows, newest first. ``rows``, ``count`` (the store's own total,
        or None when it cannot be trusted for this query) and ``filtered`` /
        ``filtered_client_side`` (which filters rode on the query and which had
        to be applied here, so an unsupported one is visible instead of silently
        ignored)."""

    @abstractmethod
    def get_order(self, ref: str) -> Dict[str, Any]:
        """One order by its id/number. ``StorefrontUnavailable`` if absent."""

    @abstractmethod
    def search_products(
        self, *, query: Optional[str] = None, category: Optional[str] = None,
        limit: int = DEFAULT_MAX_ROWS,
    ) -> List[Dict[str, Any]]:
        """Catalog rows matching a name/description search, a category, or both."""

    @abstractmethod
    def get_product(self, name: str) -> Dict[str, Any]:
        """One catalog row by its key. ``StorefrontUnavailable`` if absent."""

    def queue_board(self, statuses: List[str], days: int, limit: int) -> Dict[str, Any]:
        """How many orders sit in each state, and the oldest ones waiting.

        The one place this plugin does arithmetic, and it is a TALLY, never a sum
        of money. Two paths, and which one ran is reported, because to a shop
        owner they mean different things:

        ``source: api`` — the store filters by status and publishes a total, so
        each number is that state's whole backlog.
        ``source: page`` — it cannot, so the counts tally the most recent
        ``counted_over`` rows. An honest partial, labelled as one, beats a
        confident wrong total.

        Lives on the contract, not on one adapter, so a non-REST store cannot
        quietly invent a counting path with different provenance rules.
        """
        cleaned = [str(s).lower() for s in statuses if s]
        if cleaned and self.can_filter_status():
            api_counts: Optional[Dict[str, int]] = {}
            for status in cleaned:
                # NO days= here, on purpose. This is the shop's backlog in that
                # state, and an order that has been sitting unpaid for a month
                # is the most important thing on the board, not something to age
                # out of the count. ``days`` narrows the list of who is WAITING
                # below. And a store whose ``?status=`` is honoured can publish a
                # real total; filtering that total client-side would demote every
                # number here to a page tally.
                page = self.list_orders(status=status, limit=1)
                if page["count"] is None or "status" in page["filtered_client_side"]:
                    api_counts = None  # no trustworthy total for this state
                    break
                api_counts[status] = page["count"]
            if api_counts is not None:
                oldest = self.list_orders(status=cleaned[0], days=days, limit=limit)
                return {
                    "counts": api_counts, "source": "api",
                    "counted_over": sum(api_counts.values()),
                    "waiting": status_rows(oldest, cleaned[0], limit),
                    "statuses": cleaned,
                }
        page = self.list_orders(days=days, limit=max(limit, self.page_size))
        rows = page["rows"]
        counts = {}
        for status in cleaned or sorted({_status_of(r) for r in rows} - {""}):
            counts[status] = sum(1 for r in rows if _status_of(r) == status)
        first = cleaned[0] if cleaned else next(iter(counts), "")
        waiting = [r for r in rows if _status_of(r) == first][:max(limit, 1)]
        return {
            "counts": counts, "source": "page", "counted_over": len(rows),
            "pages": page["pages"],
            "waiting": status_rows({"rows": waiting}, first, limit),
            "statuses": cleaned,
        }


class RestStorefrontAdapter(StorefrontAdapter):
    """Generic authenticated JSON/REST storefront.

    Covers the shape most self-hosted shops present (Django REST Framework,
    Laravel Sanctum, Rails JSON, a Node API): a base URL, a token in a header,
    JSON collections at predictable paths. Everything store-specific is a
    setting, so Freshorama's ``?q=``/name-keyed-products API and a Shopify-ish
    API are two config blocks, not two adapters.
    """

    name = "rest"

    def __init__(self, settings: Dict[str, Any], token: Optional[str] = None) -> None:
        base_url = (settings.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise StorefrontUnavailable(
                "no base_url set. Add plugins.entries.shop.settings.base_url "
                "in this profile's config.yaml (the shop's own API address)."
            )
        self.base_url = base_url
        self.token = token if token is not None else (settings.get("token") or "")
        self.token_env = (settings.get("token_env") or "SHOP_API_TOKEN").strip()
        self.auth = _settings_entry(settings, "auth", {
            # "token" -> ``Authorization: Token <t>`` (DRF's default),
            # "bearer" -> ``Authorization: Bearer <t>``,
            # "header" -> a named header with no prefix (a gateway or a vendor
            # that does not speak Authorization at all).
            "style": "token", "header": "Authorization", "prefix": "Token ",
        })
        self.paths = _settings_entry(settings, "paths", DEFAULT_PATHS)
        self.filters = _settings_entry(settings, "filters", DEFAULT_FILTERS)
        self.rows_field = settings.get("rows_field") or None
        self.statuses = list(settings.get("statuses") or [])
        # Declared for the contract's counting path (StorefrontAdapter.queue_board):
        # the biggest page this store will honestly return, and whether the config
        # CLAIMS a status filter. The claim is only a claim — can_filter_status()
        # below tests it against the running store, because a shop that takes
        # ``?status=`` and ignores it would otherwise have its whole collection
        # reported as one state's backlog.
        self.declares_status_filter = bool(self.filters.get("status"))
        self._status_filter_verified: Optional[bool] = None
        try:
            self.timeout = float(settings.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            self.timeout = float(DEFAULT_TIMEOUT_SECONDS)
        try:
            self.max_rows = min(int(settings.get("max_rows") or DEFAULT_MAX_ROWS), 100)
        except (TypeError, ValueError):
            self.max_rows = DEFAULT_MAX_ROWS
        self.page_size = self.max_rows
        try:
            self.lookback_days = int(settings.get("lookback_days") or DEFAULT_LOOKBACK_DAYS)
        except (TypeError, ValueError):
            self.lookback_days = DEFAULT_LOOKBACK_DAYS

    def can_filter_status(self) -> bool:
        """Ask the store once whether ``?status=`` means anything to it.

        The probe asks for a status no shop has: a store that honours the
        parameter answers with nothing, and a store that ignores it answers with
        its whole collection — which ``list_orders`` then reports as a
        client-side filter. One cheap call, and it decides which counting path
        the queue board may use: a real total, or an honest page tally. Cached on
        the adapter because a store does not grow a filter mid-conversation.
        """
        if self._status_filter_verified is None:
            if not self.declares_status_filter:
                self._status_filter_verified = False
            else:
                try:
                    probe = self.list_orders(status=_UNPROBABLE_STATUS, limit=1)
                except StorefrontUnavailable:
                    self._status_filter_verified = False
                else:
                    self._status_filter_verified = "status" not in probe["filtered_client_side"]
        return self._status_filter_verified

    # -- transport -------------------------------------------------------

    def _url(self, path_key: str, **fmt: str) -> str:
        template = self.paths.get(path_key) or ""
        if not template:
            raise StorefrontUnavailable(f"no path configured for '{path_key}'")
        if "{ref}" in template or "{name}" in template:
            # The detail key is part of the path, so it must be escaped: a
            # product called "Mustard Honey 500g" carries a space, and an
            # unescaped one is a 404 that reads as "out of stock".
            quoted = {k: urllib.parse.quote(str(v), safe="") for k, v in fmt.items()}
            template = template.format(**quoted)
        if template.startswith(("http://", "https://")):
            return template
        return f"{self.base_url}{template}"

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if not self.token:
            return headers
        style = (self.auth.get("style") or "token").lower()
        if style == "header":
            return {str(self.auth.get("header") or "X-Api-Key"): self.token}
        prefix = self.auth.get("prefix")
        if prefix is None:
            prefix = "Bearer " if style == "bearer" else "Token "
        header = str(self.auth.get("header") or "Authorization")
        return {header: f"{prefix}{self.token}"}

    def _request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if params:
            # Drop None/empty so an unsupported filter never arrives as ``?x=``
            # (some frameworks answer that with a 400, and 400 looks like a
            # broken tool rather than a store that cannot filter).
            query = {k: v for k, v in params.items() if v not in (None, "")}
            if query:
                url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise StorefrontUnavailable(
                    f"the store refused to answer (HTTP {exc.code}) — the token in "
                    f"{self.token_env} is missing, wrong, or lacks staff permission"
                ) from exc
            if exc.code == 404:
                raise StorefrontUnavailable("the store has no such record") from exc
            raise StorefrontUnavailable(f"the store returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise StorefrontUnavailable(
                f"cannot reach the store at {self.base_url} ({exc.reason}) — is the "
                f"shop's server running, and is base_url right?"
            ) from exc
        except TimeoutError as exc:
            raise StorefrontUnavailable(
                f"the store did not answer within {self.timeout:g}s") from exc
        else:
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise StorefrontUnavailable(
                    "the store answered, but not as JSON — is base_url the API and not the website?") from exc

    # -- contract --------------------------------------------------------

    def health(self) -> bool:
        """One cheap authenticated read. Any 2xx JSON counts as alive.

        Falls back to a 1-row order query when the store publishes no health
        endpoint, because "reachable" has to mean "reachable AND the token
        works" for the setup proof to be worth running.
        """
        path_key = "health" if self.paths.get("health") else "orders"
        if path_key == "health":
            self._request(self._url("health"))
            return True
        self._request(self._url("orders"), {"limit": 1} if self.filters.get("limit") else None)
        return True

    def list_orders(self, *, status=None, phone=None, days=None, limit=None) -> Dict[str, Any]:
        limit = min(int(limit or self.max_rows), self.max_rows)
        params: Dict[str, Any] = {}
        filtered: Dict[str, Any] = {}
        client_side: List[str] = []
        # A filter rides on the query only when the store declares a parameter
        # for it. Anything it cannot do server-side is applied over the page we
        # got — and named in ``filtered_client_side``, because a filter that
        # silently does nothing is how a "0 pending orders" answer gets given to
        # a shop that has twelve.
        #
        # ``phone`` is deliberately NOT in this loop: it is always applied here,
        # on digits. A shop's own lookup is an exact string match, and in
        # Bangladesh the same customer types 01711-998877, +8801711998877 and
        # 8801711998877 in three different chats. Trusting the store's spelling
        # loses the order we were asked to find.
        for key, value in (("status", status), ("days", days)):
            param = self.filters.get(key)
            if value in (None, "") or not param:
                continue
            params[str(param)] = value
            filtered[key] = value
        if self.filters.get("limit"):
            params[str(self.filters["limit"])] = limit
        payload = self._request(self._url("orders"), params)
        rows = _extract_rows(payload, self.rows_field)
        if status:
            want = str(status).lower()
            # A store that was given ``?status=`` proved it honoured it only if
            # every row it sent back is in that state. Believing the parameter
            # instead is how "23 pending" gets read off a page containing every
            # order the shop has ever taken (Freshorama's order list is an
            # unfiltered newest-first queryset, and plenty of small shop APIs are
            # the same). Verify from the rows, filter here if they disagree.
            honoured = "status" in filtered and not any(_status_of(r) != want for r in rows)
            if not honoured:
                rows = [r for r in rows if _status_of(r) == want]
                client_side.append("status")
        if phone:
            digits = "".join(ch for ch in str(phone) if ch.isdigit())
            rows = [r for r in rows if digits and digits in _phone_digits(r)]
            client_side.append("phone")
            filtered["phone"] = phone
        if days is not None and "days" not in filtered:
            rows = _within_days(rows, int(days))
            client_side.append("days")
        count = _api_count(payload)
        return {
            "rows": rows[:limit], "limit": limit,
            # An API total is only trustworthy when every filter was honoured
            # server-side; otherwise the number would describe a different set
            # than the rows, which is worse than no number.
            "count": count if not client_side else None,
            "api_count": count,
            "filtered": filtered, "filtered_client_side": client_side,
            "pages": len(rows) >= limit,
        }

    def get_order(self, ref: str) -> Dict[str, Any]:
        # A detail endpoint answers with the object, so the object is returned
        # as-is. Envelope detection belongs to list reads only: an order row has
        # an ``items`` key, and unwrapping a detail read through it would hand
        # the agent a line item and call it the order.
        payload = self._request(self._url("order", ref=ref))
        if isinstance(payload, dict):
            if not payload or payload.get("detail"):
                raise StorefrontUnavailable(f"no order {ref}")
            return payload
        rows = _extract_rows(payload, self.rows_field)
        if rows:
            return rows[0]
        raise StorefrontUnavailable(f"no order {ref}")

    def search_products(self, *, query=None, category=None, limit=None) -> List[Dict[str, Any]]:
        limit = min(int(limit or self.max_rows), self.max_rows)
        params: Dict[str, Any] = {}
        if query and self.filters.get("search"):
            params[str(self.filters["search"])] = query
        if category and self.filters.get("category"):
            params[str(self.filters["category"])] = category
        if self.filters.get("limit"):
            params[str(self.filters["limit"])] = limit
        payload = self._request(self._url("products"), params)
        rows = _extract_rows(payload, self.rows_field)
        if query and not self.filters.get("search"):
            needle = query.lower()
            rows = [r for r in rows if needle in json.dumps(r, default=str).lower()]
        return rows[:limit]

    def get_product(self, name: str) -> Dict[str, Any]:
        payload = self._request(self._url("product", name=name))
        if isinstance(payload, dict):
            return payload
        rows = _extract_rows(payload, self.rows_field)
        if rows:
            return rows[0]
        raise StorefrontUnavailable(f"no product '{name}'")


# -- row readers (field names vary per store, so all tolerant) ----------

def _field(row: Dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _status_of(row: Dict[str, Any]) -> str:
    return str(_field(row, "status", "order_status", "state") or "").lower()


def _phone_of(row: Dict[str, Any]) -> str:
    """The customer's phone, wherever this store keeps it.

    Guest COD rows carry it at the top level; rows from a shop with a customer
    relation nest it under ``customer``/``user``/``profile``. Nested first, then
    flat: a serializer that emits both should be read from the nested object the
    customer record actually says.
    """
    for nested_key in ("customer", "user", "profile", "contact"):
        nested = row.get(nested_key)
        if isinstance(nested, dict):
            value = _field(nested, "phone", "phone_number", "mobile", "msisdn", "contact_number")
            if value:
                return str(value)
    return str(_field(row, "phone", "customer_phone", "phone_number", "contact_phone", "user_phone") or "")


def _phone_digits(row: Dict[str, Any]) -> str:
    """Digits only — a BD store writes 01711-223344, +8801711223344 and
    8801711223344 for one person, and a match must not depend on which."""
    return "".join(ch for ch in _phone_of(row) if ch.isdigit())


def _created_of(row: Dict[str, Any]) -> str:
    return str(_field(row, "created_at", "createdAt", "ordered_at", "created", "timestamp") or "")


def _parse_created(row: Dict[str, Any]) -> Optional[datetime]:
    """``created_at`` as a datetime, or None when this store writes dates in a
    shape we cannot read. Callers must handle None: an unknown-age order is
    shown, never dropped."""
    text = _created_of(row).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _within_days(rows: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    """Rows whose ``created_at`` is inside the window, newest first.

    Unparseable dates are KEPT: a store that formats dates differently must not
    silently lose its orders, and an old row shown is a smaller error than a
    live one hidden.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    kept: List[Dict[str, Any]] = []
    for row in rows:
        moment = _parse_created(row)
        if moment is None or moment >= cutoff:
            kept.append(row)
    return kept


def status_rows(result: Dict[str, Any], status: str, limit: int) -> List[Dict[str, Any]]:
    """The few fields an admin acts on per waiting order: which one, whose phone,
    what it is worth, how long it has sat.

    Every value is the store's own field copied straight through. ``total`` is
    whatever the serializer already calls the order's worth (``total``,
    ``amount``, ``grand_total``) — a shop that already folded shipping into it
    (Freshorama: ``Order.total``, shop/models.py:527) must not have it added to
    again, and a shop that did not must not have shipping guessed. Reading one
    key and never summing any is the whole difference between a bot an owner
    trusts with money and one he cannot.
    """
    out: List[Dict[str, Any]] = []
    rows = result.get("rows") or []
    # Oldest first, because a waiting list read aloud is a CALL list and the
    # order that has sat longest is the one losing the sale. Not money
    # arithmetic — an ordering of the store's own rows. Unknown age goes last:
    # a row we cannot date is never presented as more urgent than a dated one.
    # (The tuple key is safe: when one age is known and the other is not, the
    # first element decides before None is ever compared to a datetime.)
    order = [(idx, _parse_created(row)) for idx, row in enumerate(rows)]
    order.sort(key=lambda pair: (pair[1] is None, pair[1], pair[0]))
    for idx, _moment in order[:max(int(limit), 1)]:
        row = rows[idx]
        out.append({
            "ref": _field(row, "id", "order_id", "number", "order_number", "code"),
            "status": _status_of(row) or status,
            "phone": _phone_of(row),
            "total": _field(row, "total", "grand_total", "amount", "amount_total", "price"),
            "currency": _field(row, "currency") or "",
            "created_at": _created_of(row),
            "items": _field(row, "items", "order_items", "products") or [],
        })
    return out
