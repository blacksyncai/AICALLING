"""Admin-controlled platform pricing and policies (PlatformSetting rows, with safe defaults)."""

from __future__ import annotations

from sqlalchemy import select

from app.models.billing import BillingAudit, PlatformSetting

# Credits per connected minute, by LLM model. Admin-editable; these are the starting values.
DEFAULT_MODEL_RATES = {"gpt-4.1-nano": 1.0, "gpt-4.1-mini": 1.0, "gpt-4o-mini": 1.0, "gpt-4.1": 1.4, "gpt-4o": 1.5}

DEFAULTS: dict = {
    # None = paid lookups are OFF until an admin confirms a retail price.
    "property_lookup_price_cents": None,
    # "match" = charge only when an owner is found; "completed" = every completed lookup.
    "lookup_charge_policy": "match",
    "lookup_free_daily": 5,
    "model_credit_rates": DEFAULT_MODEL_RATES,
    # Extra credits/min for Premium (cloned) voices.
    "premium_voice_surcharge": 0.0,
    # Phone numbers included with any paid plan before the add-on applies.
    "included_phone_numbers": 1,
    "auto_recharge_max_monthly_cents": 200000,
}


async def get_all(db) -> dict:
    rows = (await db.execute(select(PlatformSetting))).scalars().all()
    out = dict(DEFAULTS)
    for r in rows:
        if r.key in DEFAULTS:
            out[r.key] = r.value
    return out


async def get(db, key: str):
    row = await db.get(PlatformSetting, key)
    return row.value if row is not None else DEFAULTS.get(key)


async def set_value(db, key: str, value, admin_id, reason: str) -> None:
    """Change a setting and audit it. Caller commits."""
    row = await db.get(PlatformSetting, key)
    previous = row.value if row is not None else DEFAULTS.get(key)
    if row is None:
        db.add(PlatformSetting(key=key, value=value, updated_by=admin_id))
    else:
        row.value, row.updated_by = value, admin_id
    db.add(BillingAudit(admin_id=admin_id, target="pricing", previous=f"{key}={previous}"[:64],
                        adjustment="set", new=f"{key}={value}"[:64], reason=reason))


def rate_for(rates: dict, surcharge: float, model: str | None, premium_voice: bool) -> float:
    base = float(rates.get(model or "", rates.get("gpt-4.1-mini", 1.0)))
    return round(base + (surcharge if premium_voice else 0.0), 3)
