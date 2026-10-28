"""
The single source of truth for what BlackSync sells, and how each item maps to
a real Stripe price. Nothing here creates Stripe objects: `verify()` checks
every entry against the configured Stripe account and reports what's missing or
mismatched so an admin can fix it (see admin "Stripe catalog").
"""

from __future__ import annotations

import time

from app.config import settings

# Subscription plans. `included_credits` are granted each paid billing cycle; `limits` are the
# entitlements enforced server-side (services/entitlements.py). None = no limit.
# `crm`: how many CRM connections (0 = none). Features listed are ones the app actually has.
PLANS: dict[str, dict] = {
    "solo": {
        "key": "solo", "name": "Solo", "amount_cents": 9800, "interval": "month", "included_credits": 150,
        "lookup_key": "plan_solo_monthly", "price_env": "stripe_price_solo",
        "tagline": "For one person getting started with AI calling.",
        "limits": {"agents": 2, "seats": 1, "numbers": 1, "crm": 0, "concurrency": 2, "workflows": False,
                   "advanced_workflows": False, "roles": False, "team_reporting": False, "radar": False},
        "support": "Email & ticket support",
        "features_title": "What's included",
        "features": ["Build with AI or from scratch", "Inbound and outbound campaigns", "CSV contact uploads",
                     "Live call transfers", "Calendar booking", "Recordings, transcripts and summaries",
                     "Basic analytics"],
    },
    "growth": {
        "key": "growth", "name": "Growth", "amount_cents": 19700, "interval": "month", "included_credits": 400,
        "lookup_key": "plan_growth_monthly", "price_env": "stripe_price_growth",
        "tagline": "For small teams connecting calls to their CRM.",
        "limits": {"agents": 4, "seats": 4, "numbers": 2, "crm": 1, "concurrency": 3, "workflows": True,
                   "advanced_workflows": False, "roles": False, "team_reporting": False, "radar": True},
        "support": "Priority email & ticket support",
        "features_title": "Everything in Solo, plus",
        "features": ["Radar: find the follow-ups hiding in your CRM", "1 CRM integration with syncing and field mapping", "Automated follow-ups and retries",
                     "Workflow triggers (speed-to-lead, Slack, Sheets)", "Scheduled CRM imports",
                     "Shared contact lists"],
    },
    "teams": {
        "key": "teams", "name": "Teams", "amount_cents": 34900, "interval": "month", "included_credits": 900,
        "lookup_key": "plan_teams_349_monthly", "price_env": "stripe_price_teams", "recommended": True,
        # The new $349 price goes on the existing "BlackSync Teams" product (no duplicate product).
        "reuse_product_of": "teams_legacy",
        "tagline": "For teams running calling campaigns together.",
        "limits": {"agents": 8, "seats": 10, "numbers": 4, "crm": None, "concurrency": 5, "workflows": True,
                   "advanced_workflows": True, "roles": True, "team_reporting": True, "radar": True},
        "support": "Priority human chat during business hours",
        "features_title": "Everything in Growth, plus",
        "features": ["Multiple CRMs", "Advanced automations: webhooks and the API", "Shared team campaigns",
                     "Member roles and permissions", "Team analytics by agent", "More calls at once"],
    },
    "managed": {
        "key": "managed", "name": "Managed", "amount_cents": 79700, "interval": "month", "included_credits": 1500,
        "lookup_key": "plan_managed_monthly", "price_env": "stripe_price_managed", "self_serve": False,
        # Priced per business on a call — the card shows "Custom", never the $797 floor.
        "quote_label": "Custom", "quote_note": "Tailored pricing and credit volume",
        "tagline": "We build and run your AI calling for you — for brokerages, agencies and multi-location teams.",
        "limits": {"agents": 12, "seats": 15, "numbers": 4, "crm": None, "concurrency": 8, "workflows": True,
                   "advanced_workflows": True, "roles": True, "team_reporting": True, "radar": True},
        "support": "Dedicated success manager and priority support",
        "features_title": "Everything in Teams, plus",
        "features": ["Done-for-you managed setup: agents, scripts and campaigns built for you",
                     "Broker & brokerage rollouts across agents, teams and offices",
                     "White-label options under your own brand",
                     "CRM and calendar integrations configured for you",
                     "Ongoing call reviews and script optimization",
                     "Monthly performance strategy session"],
        "scope_note": "Every Managed plan is scoped to your business on a short call. Calling credits stay usage-based.",
    },
    # The earlier $296 Teams price. Not sold any more; a subscription on it keeps Teams entitlements.
    "teams_legacy": {
        "key": "teams_legacy", "name": "Teams", "amount_cents": 29600, "interval": "month", "included_credits": 500,
        "lookup_key": "plan_teams_monthly", "legacy": True, "self_serve": False,
        "limits": None, "limits_from": "teams", "support": "Priority human chat during business hours",
        "features": [],
    },
}
PLAN_ORDER = ["solo", "growth", "teams", "managed"]
# Plans recognised on existing subscriptions but not offered.
LEGACY_PLANS = ["teams_legacy"]
# Rank for "is this an upgrade?" and suggestions.
PLAN_RANK = {"solo": 1, "growth": 2, "teams": 3, "teams_legacy": 3, "managed": 4}


def plan_limits(plan_key: str | None) -> dict | None:
    plan = PLANS.get(plan_key or "")
    if not plan:
        return None
    return dict(plan["limits"] or PLANS[plan["limits_from"]]["limits"])


def self_serve(plan_key: str) -> bool:
    plan = PLANS.get(plan_key)
    return bool(plan) and plan.get("self_serve", True) and not plan.get("legacy")


# One-time calling-credit packs (these exist in the live Stripe account).
CREDIT_PACKS: dict[str, dict] = {
    "credits_75": {"key": "credits_75", "name": "Quick Top-Up", "credits": 75, "amount_cents": 2900,
                   "lookup_key": "credits_75_one_time", "price_id": "price_1UPKcKR0Rid8tnhHK5Hgkfc5",
                    "blurb": "Runs up to 225–300 dials."},
    "credits_500": {"key": "credits_500", "name": "Standard", "credits": 500, "amount_cents": 13900,
                    "lookup_key": "credits_500_one_time", "price_id": "price_1UPKcPR0Rid8tnhHKkgMDP69",
                    "blurb": "Runs up to 1,500–2,000 dials.", "suggested": True},
    "credits_1000": {"key": "credits_1000", "name": "Volume", "credits": 1000, "amount_cents": 26000,
                     "lookup_key": "credits_1000_one_time", "price_id": "price_1UPKcRR0Rid8tnhHrol6d9g3",
                     "blurb": "Runs up to 3,000–4,000 dials."},
}
PACK_ORDER = ["credits_75", "credits_500", "credits_1000"]

# One-time lead-lookup balance top-ups. These need matching Stripe prices before they can be sold.
# Bigger packs add bonus balance: at the 12¢ list price, $5 buys ~41 records (12¢ each),
# $10 buys 100 (10¢ each) and $25 buys 312 (8¢ each).
LOOKUP_LIST_CENTS = 12
LOOKUP_FUNDS: dict[str, dict] = {
    "lookup_5": {"key": "lookup_5", "name": "$5", "amount_cents": 500, "lookup_key": "lookup_funds_5_one_time",
                 "per_record_cents": 12},
    "lookup_10": {"key": "lookup_10", "name": "$10", "amount_cents": 1000, "lookup_key": "lookup_funds_10_one_time",
                  "per_record_cents": 10},
    "lookup_25": {"key": "lookup_25", "name": "$25", "amount_cents": 2500, "lookup_key": "lookup_funds_25_one_time",
                  "per_record_cents": 8},
}
for _f in LOOKUP_FUNDS.values():
    _f["grant_cents"] = _f["amount_cents"] * LOOKUP_LIST_CENTS // _f["per_record_cents"]
    _f["records"] = _f["grant_cents"] // LOOKUP_LIST_CENTS


def lookup_grant_cents(item: dict) -> int:
    """Lookup balance a pack adds (paid amount plus its volume bonus)."""
    return item.get("grant_cents") or item["amount_cents"]


FUNDS_ORDER = ["lookup_5", "lookup_10", "lookup_25"]

PHONE_ADDON = {"key": "phone_number", "name": "Additional phone number", "amount_cents": 350, "interval": "month",
               "lookup_key": "additional_phone_number_monthly"}

# Each slot adds one to the plan's agent limit. Recurring, on the plan subscription.
AGENT_ADDON = {"key": "agent_slot", "name": "Extra agent slot", "amount_cents": 1900, "interval": "month",
               "lookup_key": "additional_agent_slot_monthly"}
# Fresh Number Pack: 10 local numbers per pack, each swapped for a new one every refresh_days, so call volume is
# spread wide and no caller ID wears out. Recurring, on the plan subscription. See services/phone_pack.
PHONE_PACK = {"key": "phone_pack", "name": "Fresh Number Pack", "amount_cents": 2500, "interval": "month",
              "numbers": 10, "refresh_days": 30, "lookup_key": "fresh_number_pack_10_monthly"}
ADDON_LOOKUP_KEYS = {PHONE_ADDON["lookup_key"], AGENT_ADDON["lookup_key"], PHONE_PACK["lookup_key"]}

# Lowest list price per credit — the fallback for $ estimates before any purchase.
LIST_CENTS_PER_CREDIT = min(p["amount_cents"] / p["credits"] for p in CREDIT_PACKS.values())


def all_items() -> list[tuple[str, dict, str]]:
    """(kind, item, expected type) for every sellable thing."""
    out = [("plan", PLANS[k], "recurring") for k in PLAN_ORDER + LEGACY_PLANS]
    out += [("credit_pack", CREDIT_PACKS[k], "one_time") for k in PACK_ORDER]
    out += [("lookup_funds", LOOKUP_FUNDS[k], "one_time") for k in FUNDS_ORDER]
    out.append(("phone_addon", PHONE_ADDON, "recurring"))
    out.append(("agent_addon", AGENT_ADDON, "recurring"))
    out.append(("phone_pack", PHONE_PACK, "recurring"))
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


def plan_for_price(price_id: str | None, prices: dict[str, dict], metadata: dict | None = None) -> str | None:
    """Our plan for a subscription's price. A custom-priced Managed subscription (made by an admin)
    is recognised by the plan named in its metadata."""
    for key in PLAN_ORDER + LEGACY_PLANS:
        if prices.get(key, {}).get("price_id") and prices[key]["price_id"] == price_id:
            return key
    named = (metadata or {}).get("plan")
    if named == "managed" and (metadata or {}).get("custom") == "1":
        return "managed"
    return None
