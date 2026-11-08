"""Radar lists reuse the provider's existing, validated contact-import filters."""
import hashlib
import json
from app.services.crm.http import CrmError
from app.services.crm import radar_discovery

PREFIX = "contacts:"
ALL = PREFIX + "all"


async def catalog(provider, http, config):
    out = ({**await provider.segment_options(http, config)} if getattr(provider, "can_segment", False)
           else {"pond": [], "source": [], "stage": [], "deal": [], "list": []})
    for kind in ("pond", "source", "stage", "deal", "list"):
        out.setdefault(kind, [])
    filters = {}
    if not radar_discovery.can_read_contacts(provider):
        return out, filters
    out["list"].append({"value": ALL, "label": "All contacts"})
    # Native list adapters already expose their richer pipeline/list catalog.
    if getattr(provider, "can_segment", False):
        return out, filters

    def add(label, selection):
        token = PREFIX + hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest()[:24]
        filters[token] = selection
        out["list"].append({"value": token, "label": label})

    for group in await provider.import_options(http, config):
        key = group.get("key")
        if not key:
            continue
        for option in group.get("options") or []:
            value = str(option.get("value") or "")
            if not value:
                continue
            selection = {key: [value]}
            label = str(option.get("label") or value)
            add(f"{group.get('label') or key} · {label}", selection)
            if group.get("type") == "pipeline" and group.get("stage_key"):
                for stage in option.get("stages") or []:
                    if stage.get("value"):
                        add(f"{label} · {stage.get('label') or stage['value']}",
                            {**selection, group["stage_key"]: [str(stage["value"])]})
    return out, filters


async def read(provider, http, config, kind, value):
    if kind == "list" and value.startswith(PREFIX):
        if not radar_discovery.can_read_contacts(provider):
            raise CrmError("This connector cannot read contact lists.")
        if value == ALL:
            filters = None
        else:
            _, available = await catalog(provider, http, config)
            if value not in available:
                raise CrmError("That CRM list is no longer available. Refresh the list picker.")
            filters = available[value]
        return await radar_discovery.contact_signals(provider, http, config, filters=filters)
    if not getattr(provider, "can_segment", False):
        raise CrmError("Choose a list from this CRM's list picker.")
    return await provider.segment_signals(http, config, kind, value)
