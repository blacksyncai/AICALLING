"""TEMPORARY read-only check (remove after it has run): is the Fresh Number Pack price findable in Stripe?"""
import structlog

log = structlog.get_logger(__name__)


async def run():
    from app.services.billing import catalog, stripe_api

    try:
        status = (await catalog.resolve_prices(force=True)).get(catalog.PHONE_PACK["key"])
        found = []
        for p in await stripe_api.list_recurring_prices():
            prod = p.get("product") or {}
            name = prod.get("name") if isinstance(prod, dict) else ""
            if "fresh" in (name or "").lower() or "number" in (name or "").lower() or p.get("unit_amount") == 2500:
                found.append({"price": p["id"], "product": name, "amount": p.get("unit_amount"),
                              "interval": (p.get("recurring") or {}).get("interval"), "lookup_key": p.get("lookup_key"),
                              "livemode": p.get("livemode")})
        log.info("pack_price_check", status=status, candidates=found[:10])
    except Exception as exc:
        log.warning("pack_price_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
