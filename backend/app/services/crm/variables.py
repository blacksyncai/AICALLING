"""
Fill an agent's {{variables}} from the CRM contact being called.

The agent's script (prompt, first message, voicemail) is read for {{variables}}. Each one is filled from a CRM
field: the account's explicit choice for that agent (Integrations → Script variables), otherwise an automatic
match by name ({{address}} → Address, {{agent_name}} → Assigned agent). The contact's CRM fields are pulled
right before the call (sync.refresh_context) and kept on the lead as custom_fields["crm_fields"][provider].
"""

from __future__ import annotations

import re

_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Always available without a CRM (contact basics, CRM notes); still mappable if the account wants.
BUILT_IN = {"name", "full_name", "company", "phone", "email", "role", "crm_context", "crm", "crm_stage", "crm_tags",
            "crm_contacted"}

# Script variable name → CRM field key, for automatic matches.
SYNONYMS = {
    "name": "first_name", "first": "first_name", "firstname": "first_name", "first_name": "first_name",
    "last": "last_name", "lastname": "last_name", "last_name": "last_name", "full_name": "full_name",
    "address": "address", "street": "address", "street_address": "address", "property_address": "address",
    "property": "address", "home_address": "address", "full_address": "full_address",
    "city": "city", "town": "city", "property_city": "city", "state": "state", "zip": "zip", "zipcode": "zip",
    "zip_code": "zip", "postal_code": "zip", "price": "price", "budget": "price", "list_price": "price",
    "home_price": "price", "source": "source", "lead_source": "source", "stage": "stage", "status": "stage",
    "tags": "tags", "agent": "assigned_agent", "agent_name": "assigned_agent", "assigned_agent": "assigned_agent",
    "realtor": "assigned_agent", "owner": "assigned_agent", "lender": "lender", "loan_officer": "lender",
    "background": "background", "notes": "background",
}

# CRM fields copied onto a contact when it's added from the CRM, so they show like CSV columns.
SHOWN = ("address", "city", "state", "zip", "price", "stage", "source", "assigned_agent")


def script_variables(agent) -> list[str]:
    """Every {{variable}} the agent's script uses, in order of first use."""
    text = " ".join(x or "" for x in (agent.system_prompt, agent.first_message, getattr(agent, "voicemail_message", ""),
                                      agent.knowledge_base))
    seen: dict[str, None] = {}
    for m in _VAR.finditer(text):
        seen.setdefault(m.group(1), None)
    return list(seen)


def auto_field(var: str, field_keys: set[str]) -> str | None:
    if var in field_keys and var not in ("name",):
        return var
    key = SYNONYMS.get(var.lower())
    return key if key in field_keys else None


def resolve(script_vars: list[str], fields: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    """{script var: value} from this contact's CRM fields. mapping[var]: a field key, "" = automatic, "-" = off."""
    out = {}
    keys = set(fields)
    for var in script_vars:
        choice = mapping.get(var, "")
        if choice == "-":
            continue
        key = choice or auto_field(var, keys)
        if key and fields.get(key):
            out[var] = fields[key]
    return out


def apply(variables: dict, lead, agent, conns: list) -> dict:
    """Variables for a call: the lead's own, then CRM values for every {{variable}} the script uses."""
    if lead is None or agent is None:
        return variables
    stored = (getattr(lead, "custom_fields", None) or {}).get("crm_fields") or {}
    if not stored:
        return variables
    script_vars = script_variables(agent)
    out = dict(variables)
    for conn in conns:
        fields = stored.get(conn.provider) or {}
        if not fields:
            continue
        mapping = ((conn.settings or {}).get("var_maps") or {}).get(str(agent.id)) or {}
        for var, value in resolve(script_vars, fields, mapping).items():
            # The CRM wins for script variables it maps; contact basics stay if the CRM has nothing.
            if var not in BUILT_IN or mapping.get(var) or not out.get(var):
                out[var] = value
    return out


_INTERNAL_KEYS = {"crm", "crm_context", "crm_context_at", "crm_fields"}


def visible_fields(custom_fields: dict | None) -> dict:
    """A contact's fields as customers see them: CSV columns and CRM-filled {{variables}}, no internals."""
    return {k: v for k, v in (custom_fields or {}).items()
            if k not in _INTERNAL_KEYS and not isinstance(v, (dict, list)) and v not in (None, "")}


def needs_prefill(lead) -> bool:
    """A CRM contact whose fields haven't been pulled yet."""
    cf = lead.custom_fields or {}
    return bool(lead.crm_refs) and not cf.get("crm_fields")
