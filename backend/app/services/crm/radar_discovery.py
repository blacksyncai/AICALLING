"""Registry-derived Radar support; new contact-reading CRM adapters work automatically."""
from app.services.crm.providers import Provider, _DNC_TAGS
from app.services.crm.radar import Signals
from app.services.contacts import normalize_phone

CONTACT_LIMIT = 500


def capabilities(provider: Provider) -> dict:
    activity = bool(provider.can_scan)
    contacts = bool(provider.can_import and type(provider).list_contacts is not Provider.list_contacts)
    mode = "activity" if activity else "contacts" if contacts else "unavailable"
    return {
        "mode": mode,
        "can_scan": activity or contacts,
        "can_segment": bool(getattr(provider, "can_segment", False)),
        "can_install": bool(provider.can_install),
        "can_map_fields": bool(provider.can_map_fields),
        "reason": "" if activity or contacts else (
            f"{provider.name} is connected, but its connector cannot read contacts yet. "
            "CRM activity discovery is unavailable for this connection."
        ),
    }


async def contact_signals(provider: Provider, http, config: dict) -> list[Signals]:
    """Use the real adapter read API, without inventing activity or call-history signals."""
    contacts = await provider.list_contacts(http, config, limit=CONTACT_LIMIT)
    out, seen = [], set()
    for c in contacts[:CONTACT_LIMIT]:
        phone = normalize_phone(c.phone)
        external_id = str(c.external_id or "")
        if not phone or not external_id or (external_id, phone) in seen:
            continue
        seen.add((external_id, phone))
        tags = [str(t) for t in c.tags or []]
        dnc = c.dnc or any(t.strip().casefold() in _DNC_TAGS for t in tags)
        out.append(Signals(
            external_id=external_id, name=c.name, phone=phone, email=c.email,
            company=c.company, created_at=c.created_at, tags=tags, status=c.stage,
            dnc=dnc, contacted=c.contacted, calls_known=False,
        ))
    return out
