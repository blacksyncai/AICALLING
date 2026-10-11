"""
The single source of truth for what BlackSync sells, and how each item maps to
a real Stripe price. Nothing here creates Stripe objects: `verify()` checks
every entry against the configured Stripe account and reports what's missing or
mismatched so an admin can fix it (see admin "Stripe catalog").
"""

from __future__ import annotations

import time

from app.config import settings

# Subscription plans. `included_credits` are granted each paid billing cycle.
# Features listed are ones the app actually has today.
PLANS: dict[str, dict] = {
    "solo": {
        "key": "solo", "name": "Solo", "amount_cents": 9800, "interval": "month", "included_credits": 150,
        "lookup_key": "plan_solo_monthly", "price_env": "stripe_price_solo",
        "features": ["150 calling credits included every billing cycle", "AI calling agents", "Agent configuration and management",
                     "Calling campaigns", "Usage reporting", "Buy additional credits any time"],
    },
    "teams": {
        "key": "teams", "name": "Teams", "amount_cents": 29600, "interval": "month", "included_credits": 700,
        "lookup_key": "plan_teams_monthly", "price_env": "stripe_price_teams",
        "features": ["700 calling credits included every billing cycle", "Team agent management", "Invite team members",
                     "Calling campaigns", "Usage reporting", "Buy additional credits any time"],
    },
}
PLAN_ORDER = ["solo", "teams"]

# One-time calling-credit packs (these exist in the live Stripe account).
CREDIT_PACKS: dict[str, dict] = {
    "credits_100": {"key": "credits_100", "name": "Quick Top-Up", "credits": 100, "amount_cents": 2900,
                    "lookup_key": "credits_100_one_time", "price_id": "price_1UPKcKR0Rid8tnhHK5Hgkfc5",
                    "blurb": "For occasional use and inbound agents."},
    "credits_500": {"key": "credits_500", "name": "Standard", "credits": 500, "amount_cents": 13900,
                    "lookup_key": "credits_500_one_time", "price_id": "price_1UPKcPR0Rid8tnhHKkgMDP69",
                    "blurb": "For regular calling.", "suggested": True},
    "credits_1000": {"key": "credits_1000", "name": "Volume", "credits": 1000, "amount_cents": 26000,
                     "lookup_key": "credits_1000_one_time", "price_id": "price_1UPKcRR0Rid8tnhHrol6d9g3",
                     "blurb": "For higher-volume campaigns."},
}
PACK_ORDER = ["credits_100", "credits_500", "credits_1000"]

# One-time lead-lookup balance top-ups. These need matching Stripe prices before they can be sold.
LOOKUP_FUNDS: dict[str, dict] = {
    "lookup_5": {"key": "lookup_5", "name": "$5", "amount_cents": 500, "lookup_key": "lookup_funds_5_one_time"},
    "lookup_10": {"key": "lookup_10", "name": "$10", "amount_cents": 1000, "lookup_key": "lookup_funds_10_one_time"},
    "lookup_25": {"key": "lookup_25", "name": "$25", "amount_cents": 2500, "lookup_key": "lookup_funds_25_one_time"},
}
FUNDS_ORDER = ["lookup_5", "lookup_10", "lookup_25"]

PHONE_ADDON = {"key": "phone_number", "name": "Additional phone number", "amount_cents": 350, "interval": "month",
               "lookup_key": "additional_phone_number_monthly"}

# Lowest list price per credit — the fallback for $ estimates before any purchase.
LIST_CENTS_PER_CREDIT = min(p["amount_cents"] / p["credits"] for p in CREDIT_PACKS.values())


def all_items() -> list[tuple[str, dict, str]]:
    """(kind, item, expected type) for every sellable thing."""
    out = [("plan", PLANS[k], "recurring") for k in PLAN_ORDER]
    out += [("credit_pack", CREDIT_PACKS[k], "one_time") for k in PACK_ORDER]
    out += [("lookup_funds", LOOKUP_FUNDS[k], "one_time") for k in FUNDS_ORDER]
    out.append(("phone_addon", PHONE_ADDON, "recurring"))
    return out


# ── Verification against Stripe (cached) ─────────────────────────────────────

_CACHE: dict = {"at": 0.0, "prices": {}}
_TTL = 600


async def resolve_prices(force: bool = False) -> dict[str, dict]:
    """item key → {"price_id", "status": ok|missing|mismatch|unconfigured, "detail", "active"}."""
    from app.services.billing import stripe_api

    if not stripe_api.ready():
        return {item["key"]: {"price_id": None, "status": "unconfigured", "detail": "Stripe isn't connected yet."}
                for _, item, _ in all_items()}
    if not force and _CACHE["prices"] and time.time() - _CACHE["at"] < _TTL:
        return _CACHE["prices"]

    keys = [item["lookup_key"] for _, item, _ in all_items()]
    by_lookup = await stripe_api.prices_by_lookup_keys(keys)
    out: dict[str, dict] = {}
    for kind, item, expected_type in all_items():
        explicit = item.get("price_id") or (getattr(settings, item["price_env"], "") if item.get("price_env") else "")
        price = None
        if explicit:
            price = await stripe_api.retrieve_price(explicit)
        if price is None:
            price = by_lookup.get(item["lookup_key"])
        if price is None:
            out[item["key"]] = {"price_id": None, "status": "missing",
                                "detail": f"No active Stripe price with lookup key {item['lookup_key']}" +
                                          (f" or id {explicit}" if explicit else "") + "."}
            continue
        problems = []
        if not price.get("active", False):
            problems.append("price is archived")
        if price.get("unit_amount") != item["amount_cents"]:
            problems.append(f"amount is {price.get('unit_amount')}¢, expected {item['amount_cents']}¢")
        if (price.get("currency") or "").lower() != "usd":
            problems.append(f"currency is {price.get('currency')}")
        if price.get("type") != expected_type:
            problems.append(f"type is {price.get('type')}, expected {expected_type}")
        if explicit and price.get("lookup_key") and price["lookup_key"] != item["lookup_key"]:
            problems.append(f"lookup key is {price['lookup_key']}, expected {item['lookup_key']}")
        out[item["key"]] = {"price_id": price["id"], "status": "mismatch" if problems else "ok",
                            "detail": "; ".join(problems) or "Matches Stripe.", "active": price.get("active", False),
                            "product": price.get("product")}
    _CACHE.update(at=time.time(), prices=out)
    return out


def invalidate() -> None:
    _CACHE.update(at=0.0, prices={})


async def sellable_price(key: str) -> str:
    """The verified Stripe price id for an item, or raise NotSellable with a plain reason."""
    info = (await resolve_prices()).get(key)
    if not info or info["status"] != "ok":
        raise NotSellable("This option isn't available to buy yet." if not info or info["status"] != "unconfigured"
                          else "Payments aren't set up yet.")
    return info["price_id"]


class NotSellable(Exception):
    pass


def plan_for_price(price_id: str | None, prices: dict[str, dict]) -> str | None:
    for key in PLAN_ORDER:
        if prices.get(key, {}).get("price_id") and prices[key]["price_id"] == price_id:
            return key
    return None
