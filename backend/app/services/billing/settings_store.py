"""Admin-controlled platform pricing and policies (PlatformSetting rows, with safe defaults)."""

from __future__ import annotations

from sqlalchemy import select

from app.models.billing import BillingAudit, PlatformSetting

# Credits per connected minute, by LLM model (1.0–1.3). Admin-editable; these are the starting values.
DEFAULT_MODEL_RATES = {"gpt-4.1-nano": 1.0, "gpt-4.1-mini": 1.0, "gpt-4o-mini": 1.0, "gpt-4.1": 1.2, "gpt-4o": 1.2,
                       "claude-haiku-5-5": 1.0, "claude-sonnet-5-5": 1.3,
                       "gpt-oss-120b": 1.2, "qwen-3.8-27b": 1.0}
# Earlier defaults; a saved copy of one of them follows the current defaults instead.
_LEGACY_MODEL_RATES = [
    {"gpt-4.1-nano": 1.0, "gpt-4.1-mini": 1.0, "gpt-4o-mini": 1.0, "gpt-4.1": 1.4, "gpt-4o": 1.5},
    {"gpt-4.1-nano": 1.0, "gpt-4.1-mini": 1.0, "gpt-4o-mini": 1.0, "gpt-4.1": 1.2, "gpt-4o": 1.3},
    {"gpt-4.1-nano": 1.0, "gpt-4.1-mini": 1.0, "gpt-4o-mini": 1.0, "gpt-4.1": 1.2, "gpt-4o": 1.2},
]

DEFAULTS: dict = {
    # None = paid lookups are OFF until an admin confirms a retail price.
    "property_lookup_price_cents": 12,
    # "match" = charge only when an owner is found; "completed" = every completed lookup.
    "lookup_charge_policy": "match",
    "lookup_free_daily": 5,
    "model_credit_rates": DEFAULT_MODEL_RATES,
    # Extra credits/min for Premium (cloned) voices.
    "premium_voice_surcharge": 0.0,
    # Phone numbers included with any paid plan before the add-on applies.
    "included_phone_numbers": 1,
    "auto_recharge_max_monthly_cents": 200000,
    # Let account managers buy numbers themselves (off = they request one and an admin assigns it).
    "self_serve_numbers": False,
    # Phone line (Twilio) fee: credits per started minute of a connected phone call, on top of the AI rate.
    "phone_minute_fee": 0.08,
    # Phone calls shorter than this (and voicemails) aren't charged AI time — only the phone line fee.
    "min_ai_billable_seconds": 10,
    # Browser test minutes each account gets free; after that tests use credits at the AI rate (no phone fee).
    "free_test_minutes": 10,
    # Free calling credits for a self-serve signup (no card).
    "trial_credits": 30,
    "max_numbers_per_org": 5,
}


async def get_all(db) -> dict:
    rows = (await db.execute(select(PlatformSetting))).scalars().all()
    out = dict(DEFAULTS)
    for r in rows:
        if r.key in DEFAULTS:
            out[r.key] = _current(r.key, r.value)
    return out


def _current(key: str, value):
    if key != "model_credit_rates":
        return value
    if value in _LEGACY_MODEL_RATES:
        return DEFAULT_MODEL_RATES
    # Models added after the admin saved their rates start at the default rate.
    return {**DEFAULT_MODEL_RATES, **(value or {})}


async def get(db, key: str):
    row = await db.get(PlatformSetting, key)
    return _current(key, row.value) if row is not None else DEFAULTS.get(key)


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
