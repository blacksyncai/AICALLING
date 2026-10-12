"""
CRM / app adapters. Each provider knows how to:

- verify a connection (returns a label like "Acme Realty · jo@acme.com"),
- find or create a contact for a called number,
- log a finished call on that contact (call activity and/or note),
- list contacts (import, and new leads for speed-to-lead).

Paths are relative to the provider's API root so the same code runs natively
(API key) or through Nango's proxy (OAuth). See http.py.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from app.services.contacts import normalize_phone
from app.services.crm.http import BaseHttp, CrmError, NangoHttp, NativeHttp

UTC = dt.timezone.utc
_DNC_TAGS = {"dnc", "do not call", "do-not-call", "donotcall", "do not contact", "dnd"}


@dataclass
class Contact:
    name: str = ""
    phone: str = ""
    email: str = ""
    company: str = ""
    external_id: str = ""
    created_at: dt.datetime | None = None
    tags: list[str] = field(default_factory=list)
    stage: str = ""
    dnc: bool = False               # marked do-not-call / bad number in the CRM
    contacted: bool | None = None   # the CRM shows earlier contact (None = unknown)


@dataclass
class CallInfo:
    call_id: str
    outcome: str = ""
    summary: str = ""
    duration_seconds: int = 0
    phone: str = ""
    agent_name: str = ""
    meeting_time: str = ""
    meeting_link: str = ""
    started_at: dt.datetime | None = None
    url: str = ""
    extracted: dict = field(default_factory=dict)

    @property
    def outcome_label(self) -> str:
        return OUTCOME_LABELS.get(self.outcome or "", (self.outcome or "Completed").replace("_", " ").title())

    @property
    def connected(self) -> bool:
        return self.outcome not in ("no_answer", "failed", "voicemail") and self.duration_seconds > 0

    def note(self, html: bool = False) -> str:
        m, s = divmod(int(self.duration_seconds or 0), 60)
        lines = [f"BlackSync AI call: {self.outcome_label}",
                 f"Agent: {self.agent_name or 'AI agent'} · Duration {m}:{s:02d}"]
        if self.meeting_time:
            lines.append(f"Meeting: {self.meeting_time}" + (f" ({self.meeting_link})" if self.meeting_link else ""))
        if self.summary:
            lines += ["", self.summary]
        details = [f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in (self.extracted or {}).items()
                   if v not in (None, "", [], {}) and not isinstance(v, (dict, list))]
        if details:
            lines += ["", *details[:12]]
        if self.url:
            lines += ["", f"Call details and recording: {self.url}"]
        text = "\n".join(lines)
        if html:
            from html import escape
            return "<br>".join(escape(x) for x in text.split("\n"))
        return text


OUTCOME_LABELS = {
    "meeting_booked": "Meeting booked", "interested": "Interested", "not_interested": "Not interested",
    "callback": "Callback requested", "no_answer": "No answer", "voicemail": "Left voicemail",
    "failed": "Call failed", "completed": "Completed", "qualified": "Qualified", "not_qualified": "Not qualified",
    "do_not_call": "Asked not to be called", "wrong_number": "Wrong number", "transferred": "Transferred",
}


def split_name(name: str) -> tuple[str, str]:
    parts = (name or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _digits(p: str) -> str:
    return "".join(ch for ch in p or "" if ch.isdigit())


def _parse_time(v: Any) -> dt.datetime | None:
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):
            return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=UTC)
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T", 1))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except (ValueError, OverflowError):
        return None


@dataclass
class AuthField:
    name: str
    label: str
    secret: bool = True
    placeholder: str = ""
    help: str = ""


class Provider:
    key = ""
    name = ""
    category = "crm"
    description = ""
    auth_fields: list[AuthField] = []
    nango_providers: tuple[str, ...] = ()  # Nango provider names this adapter can drive
    native = True
    can_import = True
    can_new_leads = True
    docs_url = ""

    def http(self, secret: str, config: dict) -> BaseHttp:
        if config.get("nango_connection_id"):
            return NangoHttp(config["nango_integration"], config["nango_connection_id"], headers=self.nango_headers())
        return self.native_http(secret, config)

    def nango_headers(self) -> dict:
        return {}

    def native_http(self, secret: str, config: dict) -> BaseHttp:
        raise CrmError(f"{self.name} connects through OAuth only.")

    async def verify(self, http: BaseHttp, config: dict) -> str:
        raise NotImplementedError

    async def find_or_create(self, http: BaseHttp, config: dict, c: Contact, create: bool) -> str | None:
        raise NotImplementedError

    async def log_call(self, http: BaseHttp, config: dict, external_id: str, call: CallInfo) -> None:
        raise NotImplementedError

    async def list_contacts(self, http: BaseHttp, config: dict, limit: int = 500,
                            since: dt.datetime | None = None, filters: dict | None = None) -> list[Contact]:
        raise NotImplementedError

    async def import_options(self, http: BaseHttp, config: dict) -> list[dict]:
        """Filters the import dialog offers: [{key, label, type: multi|single, options: [{value, label}]}]."""
        return []

    async def mark_dnc(self, http: BaseHttp, config: dict, external_id: str) -> None:
        """Flag the contact as do-not-call in the CRM (when the CRM has a way to)."""
        return None


# ── Close ─────────────────────────────────────────────────────────────────────


class Close(Provider):
    key, name = "close", "Close"
    description = "Log every AI call on the lead with the summary and outcome, and import leads to call."
    auth_fields = [AuthField("api_key", "API key", placeholder="api_…", help="Close → Settings → Developer → API Keys.")]
    nango_providers = ("close",)
    docs_url = "https://developer.close.com"

    def native_http(self, secret, config):
        return NativeHttp("https://api.close.com/api", basic=(secret, ""))

    async def verify(self, http, config):
        me = await http.request("GET", "/v1/me/")
        org = ((me.get("organizations") or [{}])[0] or {}).get("name", "")
        who = " ".join(x for x in (me.get("first_name"), me.get("last_name")) if x) or me.get("email", "")
        return " · ".join(x for x in (org, who) if x)

    async def find_or_create(self, http, config, c, create):
        if c.phone:
            found = await http.request("GET", "/v1/lead/", params={"query": f'phone_number:"{c.phone}"', "_limit": 1,
                                                                   "_fields": "id"})
            if found.get("data"):
                return found["data"][0]["id"]
        if c.email:
            found = await http.request("GET", "/v1/lead/", params={"query": f'email_address:"{c.email}"', "_limit": 1,
                                                                   "_fields": "id"})
            if found.get("data"):
                return found["data"][0]["id"]
        if not create:
            return None
        contact: dict = {"name": c.name or c.phone}
        if c.phone:
            contact["phones"] = [{"phone": c.phone, "type": "mobile"}]
        if c.email:
            contact["emails"] = [{"email": c.email, "type": "office"}]
        lead = await http.request("POST", "/v1/lead/", json={"name": c.company or c.name or c.phone, "contacts": [contact]})
        return lead["id"]

    async def log_call(self, http, config, external_id, call):
        body = {"lead_id": external_id, "direction": "outbound", "status": "completed",
                "duration": int(call.duration_seconds or 0), "phone": call.phone, "note": call.note()}
        if call.started_at:
            body["date_created"] = call.started_at.isoformat()
        try:
            await http.request("POST", "/v1/activity/call/", json=body)
        except CrmError as exc:
            if exc.status in (401, 403):
                raise
            await http.request("POST", "/v1/activity/note/", json={"lead_id": external_id, "note": call.note()})

    _LEAD_FIELDS = ["id", "display_name", "contacts", "date_created", "status_label"]

    async def import_options(self, http, config):
        out = []
        try:
            st = (await http.request("GET", "/v1/status/lead/")).get("data") or []
            out.append({"key": "status", "label": "Lead statuses", "type": "multi",
                        "options": [{"value": x["label"], "label": x["label"]} for x in st]})
        except CrmError:
            pass
        try:
            pipes = (await http.request("GET", "/v1/pipeline/")).get("data") or []
            opts = [{"value": st["id"], "label": f"{p.get('name') or 'Pipeline'} · {st.get('label') or st['id']}"}
                    for p in pipes for st in p.get("statuses") or [] if st.get("id")]
            if opts:
                out.append({"key": "opp_status", "label": "Pipeline stage (opportunities)", "type": "multi", "options": opts})
        except CrmError:
            pass
        try:
            views = (await http.request("GET", "/v1/saved_search/", params={"_limit": 200})).get("data") or []
            usable = [v for v in views if v.get("s_query") or (isinstance(v.get("query"), str) and v["query"].strip())]
            if usable:
                out.append({"key": "view", "label": "Smart view", "type": "single",
                            "options": [{"value": v["id"], "label": v.get("name") or "Smart view"} for v in usable]})
        except CrmError:
            pass
        return out

    @staticmethod
    def _contacts_of(lead: dict) -> list[Contact]:
        status = lead.get("status_label") or ""
        dnc = any(w in status.lower() for w in ("do not call", "dnc", "do not contact"))
        out = []
        for ct in lead.get("contacts") or []:
            phones = [p.get("phone") for p in ct.get("phones") or [] if p.get("phone")]
            if not phones:
                continue
            emails = [e.get("email") for e in ct.get("emails") or [] if e.get("email")]
            out.append(Contact(ct.get("name") or lead.get("display_name", ""), phones[0], (emails or [""])[0],
                               lead.get("display_name", ""), lead["id"], _parse_time(lead.get("date_created")),
                               stage=status, dnc=dnc))
        return out

    async def _view_leads(self, http, view_id: str, cap: int):
        """Leads in a smart view (both classic query views and newer filter-builder views)."""
        view = await http.request("GET", f"/v1/saved_search/{view_id}/")
        if isinstance(view.get("query"), str) and view["query"].strip() and not view.get("s_query"):
            async for lead in self._query_leads(http, view["query"], cap):
                yield lead
            return
        cursor, seen = None, 0
        while seen < cap:
            body: dict = {"query": view.get("s_query"), "_fields": {"lead": self._LEAD_FIELDS}, "_limit": 200}
            if cursor:
                body["cursor"] = cursor
            page = await http.request("POST", "/v1/data/search/", json=body)
            for lead in page.get("data") or []:
                if lead.get("id", "").startswith("lead_") or "contacts" in lead:
                    seen += 1
                    yield lead
            cursor = page.get("cursor")
            if not cursor:
                break

    async def _query_leads(self, http, query: str, cap: int):
        skip = 0
        while skip < cap:
            params = {"_limit": 100, "_skip": skip, "_fields": ",".join(self._LEAD_FIELDS)}
            if query:
                params["query"] = query
            page = await http.request("GET", "/v1/lead/", params=params)
            for lead in page.get("data") or []:
                yield lead
            if not page.get("has_more"):
                break
            skip += 100

    async def _stage_lead_ids(self, http, status_ids: list[str], cap: int = 2000) -> list[str]:
        ids: list[str] = []
        for sid in status_ids:
            skip = 0
            while len(ids) < cap:
                page = await http.request("GET", "/v1/opportunity/", params={"status_id": sid, "_limit": 100, "_skip": skip,
                                                                            "_fields": "lead_id"})
                ids += [o["lead_id"] for o in page.get("data") or [] if o.get("lead_id")]
                if not page.get("has_more"):
                    break
                skip += 100
        return list(dict.fromkeys(ids))

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        f = filters or {}
        statuses = set(f.get("status") or [])
        view = (f.get("view") or [""])[0] if isinstance(f.get("view"), list) else (f.get("view") or "")
        stage_ids = list(f.get("opp_status") or [])
        stage_leads = set(await self._stage_lead_ids(http, stage_ids)) if stage_ids else None
        cap = max(limit * 3, 300)

        def keep(lead: dict) -> bool:
            if statuses and (lead.get("status_label") or "") not in statuses:
                return False
            if stage_leads is not None and lead.get("id") not in stage_leads:
                return False
            created = _parse_time(lead.get("date_created"))
            return not (since and created and created <= since)

        out: list[Contact] = []
        if view:
            source = self._view_leads(http, view, cap)
        elif stage_leads is not None and not statuses:
            async def by_id():
                for lid in list(stage_leads)[:cap]:
                    try:
                        yield await http.request("GET", f"/v1/lead/{lid}/", params={"_fields": ",".join(self._LEAD_FIELDS)})
                    except CrmError as exc:
                        if exc.status in (401, 403):
                            raise
            source = by_id()
        else:
            parts = []
            if since:
                parts.append(f'created > "{since.strftime("%Y-%m-%d %H:%M:%S")}"')
            if statuses:
                parts.append("(" + " or ".join(f'lead_status:"{x}"' for x in statuses) + ")")
            source = self._query_leads(http, " ".join(parts), cap)
        async for lead in source:
            if keep(lead):
                out += self._contacts_of(lead)
            if len(out) >= limit:
                break
        return out[:limit]


# ── Follow Up Boss ────────────────────────────────────────────────────────────

_FUB_OUTCOMES = {"meeting_booked": "Interested", "interested": "Interested", "callback": "Interested",
                 "not_interested": "Not Interested", "no_answer": "No Answer", "voicemail": "Left Message",
                 "wrong_number": "Bad Number", "failed": "No Answer"}


class FollowUpBoss(Provider):
    key, name = "followupboss", "Follow Up Boss"
    description = "Log AI calls and notes on the person, create new people, import leads and auto-call new ones."
    auth_fields = [AuthField("api_key", "API key", placeholder="fka_…", help="Follow Up Boss → Admin → API → Create API key.")]
    docs_url = "https://docs.followupboss.com"

    def native_http(self, secret, config):
        return NativeHttp("https://api.followupboss.com", basic=(secret, ""),
                          headers={"X-System": "BlackSync"})

    async def verify(self, http, config):
        me = await http.request("GET", "/v1/me")
        return " · ".join(x for x in (me.get("account", {}).get("name") if isinstance(me.get("account"), dict) else "",
                                      me.get("name"), me.get("email")) if x)

    async def find_or_create(self, http, config, c, create):
        for params in ({"phone": _digits(c.phone)[-10:]} if c.phone else None, {"email": c.email} if c.email else None):
            if not params:
                continue
            found = await http.request("GET", "/v1/people", params={**params, "limit": 1, "fields": "id"})
            if found.get("people"):
                return str(found["people"][0]["id"])
        if not create:
            return None
        first, last = split_name(c.name)
        # /events is FUB's lead-intake endpoint: it de-duplicates and runs the account's lead routing.
        person: dict = {"firstName": first, "lastName": last}
        if c.phone:
            person["phones"] = [{"value": c.phone}]
        if c.email:
            person["emails"] = [{"value": c.email}]
        ev = await http.request("POST", "/v1/events", json={"source": "BlackSync AI", "system": "BlackSync",
                                                            "type": "General Inquiry", "person": person})
        pid = (ev.get("person") or {}).get("id") or ev.get("personId") or ev.get("id")
        if not pid:
            raise CrmError("Follow Up Boss didn't return the new person.")
        return str(pid)

    async def log_call(self, http, config, external_id, call):
        body = {"personId": int(external_id), "phone": call.phone, "isIncoming": False,
                "duration": int(call.duration_seconds or 0), "note": call.note()}
        if call.outcome in _FUB_OUTCOMES:
            body["outcome"] = _FUB_OUTCOMES[call.outcome]
        await http.request("POST", "/v1/calls", json=body)
        if call.connected and call.summary:
            await http.request("POST", "/v1/notes", json={"personId": int(external_id),
                                                         "subject": f"AI call: {call.outcome_label}", "body": call.note()})

    async def import_options(self, http, config):
        async def get(path, key):
            try:
                return (await http.request("GET", path, params={"limit": 100})).get(key) or []
            except CrmError:
                return []
        stages, ponds, users = await get("/v1/stages", "stages"), await get("/v1/ponds", "ponds"), await get("/v1/users", "users")
        tags: dict[str, int] = {}
        try:
            sample = await http.request("GET", "/v1/people", params={"limit": 100, "sort": "-updated", "fields": "id,tags"})
            for p in sample.get("people") or []:
                for t in p.get("tags") or []:
                    tags[t] = tags.get(t, 0) + 1
        except CrmError:
            pass
        out = [{"key": "stage", "label": "Stages", "type": "multi", "options": [{"value": x["name"], "label": x["name"]} for x in stages]},
               {"key": "tags", "label": "Tags", "type": "multi", "free": True,
                "options": [{"value": t, "label": t} for t in sorted(tags, key=lambda t: -tags[t])[:60]]}]
        if ponds:
            out.append({"key": "pond", "label": "Ponds", "type": "multi",
                        "options": [{"value": str(x["id"]), "label": x.get("name") or str(x["id"])} for x in ponds]})
        if users:
            out.append({"key": "agent", "label": "Assigned agent", "type": "multi",
                        "options": [{"value": str(x["id"]), "label": x.get("name") or x.get("email", "")} for x in users]})
        return out

    async def mark_dnc(self, http, config, external_id):
        person = await http.request("GET", f"/v1/people/{int(external_id)}", params={"fields": "id,tags"})
        tags = list(dict.fromkeys([*(person.get("tags") or []), "Do Not Call"]))
        await http.request("PUT", f"/v1/people/{int(external_id)}", json={"tags": tags})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        f = filters or {}
        want_stage, want_tags = set(f.get("stage") or []), {t.lower() for t in f.get("tags") or []}
        want_pond, want_agent = set(f.get("pond") or []), set(f.get("agent") or [])
        out: list[Contact] = []
        offset, pages = 0, 0
        while len(out) < limit and pages < 40:
            params: dict = {"limit": 100, "offset": offset, "sort": "-created",
                            "fields": "id,name,firstName,lastName,phones,emails,created,stage,tags,assignedPondId,assignedUserId,contacted"}
            if len(want_stage) == 1:
                params["stage"] = next(iter(want_stage))
            if len(want_pond) == 1:
                params["assignedPondId"] = next(iter(want_pond))
            page = await http.request("GET", "/v1/people", params=params)
            pages += 1
            people = page.get("people") or []
            stop = False
            for p in people:
                created = _parse_time(p.get("created"))
                if since and created and created <= since:
                    stop = True
                    break
                tags = [t for t in p.get("tags") or [] if isinstance(t, str)]
                if want_stage and p.get("stage") not in want_stage:
                    continue
                if want_tags and not want_tags & {t.lower() for t in tags}:
                    continue
                if want_pond and str(p.get("assignedPondId") or "") not in want_pond:
                    continue
                if want_agent and str(p.get("assignedUserId") or "") not in want_agent:
                    continue
                phones = [x for x in p.get("phones") or [] if x.get("value")]
                good = [x["value"] for x in phones if str(x.get("status") or "").lower() not in ("not valid", "bad", "invalid")]
                if not phones:
                    continue
                emails = [x.get("value") for x in p.get("emails") or [] if x.get("value")]
                name = p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x)
                dnc = (not good) or (p.get("stage") or "").lower() == "trash" or bool(_DNC_TAGS & {t.lower() for t in tags})
                out.append(Contact(name, (good or [phones[0]["value"]])[0], (emails or [""])[0], "", str(p["id"]), created,
                                   tags=tags, stage=p.get("stage") or "", dnc=dnc, contacted=bool(p.get("contacted"))))
            if stop or len(people) < 100:
                break
            offset += 100
        return out[:limit]


# ── HubSpot ───────────────────────────────────────────────────────────────────


class HubSpot(Provider):
    key, name = "hubspot", "HubSpot"
    description = "Log AI calls on the contact's timeline, create contacts and import contacts to call."
    auth_fields = [AuthField("api_key", "Private app access token", placeholder="pat-na1-…",
                             help="HubSpot → Settings → Integrations → Private apps. Scopes: crm.objects.contacts.read/write.")]
    nango_providers = ("hubspot",)
    docs_url = "https://developers.hubspot.com/docs/api/crm/calls"

    def native_http(self, secret, config):
        return NativeHttp("https://api.hubapi.com", headers={"Authorization": f"Bearer {secret}"})

    async def verify(self, http, config):
        info = await http.request("GET", "/account-info/v3/details")
        return f"HubSpot account {info.get('portalId', '')}".strip()

    async def _search(self, http, prop: str, value: str) -> str | None:
        res = await http.request("POST", "/crm/v3/objects/contacts/search", json={
            "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}], "limit": 1})
        rows = res.get("results") or []
        return str(rows[0]["id"]) if rows else None

    async def find_or_create(self, http, config, c, create):
        if c.email and (hit := await self._search(http, "email", c.email)):
            return hit
        if c.phone:
            for v in (c.phone, _digits(c.phone)[-10:]):
                if hit := await self._search(http, "phone", v):
                    return hit
        if not create:
            return None
        first, last = split_name(c.name)
        props = {k: v for k, v in {"firstname": first, "lastname": last, "phone": c.phone, "email": c.email,
                                   "company": c.company}.items() if v}
        created = await http.request("POST", "/crm/v3/objects/contacts", json={"properties": props})
        return str(created["id"])

    async def log_call(self, http, config, external_id, call):
        ts = (call.started_at or dt.datetime.now(UTC)).astimezone(UTC).isoformat()
        await http.request("POST", "/crm/v3/objects/calls", json={
            "properties": {
                "hs_timestamp": ts, "hs_call_title": f"AI call: {call.outcome_label}", "hs_call_body": call.note(html=True),
                "hs_call_duration": str(int(call.duration_seconds or 0) * 1000), "hs_call_direction": "OUTBOUND",
                "hs_call_status": "COMPLETED" if call.connected else "NO_ANSWER", "hs_call_to_number": call.phone,
            },
            "associations": [{"to": {"id": external_id},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 194}]}],
        })

    async def import_options(self, http, config):
        out = []
        for prop, label in (("lifecyclestage", "Lifecycle stage"), ("hs_lead_status", "Lead status")):
            try:
                d = await http.request("GET", f"/crm/v3/properties/contacts/{prop}")
                opts = [{"value": o["value"], "label": o.get("label") or o["value"]} for o in d.get("options") or [] if not o.get("hidden")]
                if opts:
                    out.append({"key": prop, "label": label, "type": "multi", "options": opts})
            except CrmError:
                pass
        try:
            owners = (await http.request("GET", "/crm/v3/owners", params={"limit": 100})).get("results") or []
            if owners:
                out.append({"key": "hubspot_owner_id", "label": "Contact owner", "type": "multi", "options": [
                    {"value": str(o["id"]), "label": " ".join(x for x in (o.get("firstName"), o.get("lastName")) if x) or o.get("email", "")}
                    for o in owners]})
        except CrmError:
            pass
        return out

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        f = filters or {}
        out: list[Contact] = []
        after = None
        props = ["firstname", "lastname", "phone", "mobilephone", "email", "company", "createdate", "lifecyclestage",
                 "hs_lead_status", "notes_last_contacted"]
        conds = []
        if since:
            conds.append({"propertyName": "createdate", "operator": "GT", "value": str(int(since.timestamp() * 1000))})
        for key in ("lifecyclestage", "hs_lead_status", "hubspot_owner_id"):
            if f.get(key):
                conds.append({"propertyName": key, "operator": "IN", "values": list(f[key])})
        if f.get("skip_contacted"):
            conds.append({"propertyName": "notes_last_contacted", "operator": "NOT_HAS_PROPERTY"})
        while len(out) < limit:
            body: dict = {"limit": 100, "properties": props, "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}]}
            if conds:
                body["filterGroups"] = [{"filters": conds}]
            if after:
                body["after"] = after
            page = await http.request("POST", "/crm/v3/objects/contacts/search", json=body)
            for r in page.get("results") or []:
                p = r.get("properties") or {}
                phone = p.get("phone") or p.get("mobilephone")
                if not phone:
                    continue
                name = " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x)
                status = p.get("hs_lead_status") or ""
                out.append(Contact(name, phone, p.get("email") or "", p.get("company") or "", str(r["id"]),
                                   _parse_time(p.get("createdate")), stage=p.get("lifecyclestage") or "",
                                   dnc=status.upper() in ("UNQUALIFIED_DNC", "DO_NOT_CALL"),
                                   contacted=bool(p.get("notes_last_contacted"))))
            after = ((page.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                break
        return out[:limit]


# ── Pipedrive ─────────────────────────────────────────────────────────────────


class Pipedrive(Provider):
    key, name = "pipedrive", "Pipedrive"
    description = "Log AI calls as done activities with notes on the person, and import people to call."
    auth_fields = [AuthField("api_key", "API token", help="Pipedrive → Personal preferences → API.")]
    nango_providers = ("pipedrive",)
    docs_url = "https://developers.pipedrive.com/docs/api/v1"

    def native_http(self, secret, config):
        return NativeHttp("https://api.pipedrive.com", params={"api_token": secret})

    async def verify(self, http, config):
        me = (await http.request("GET", "/v1/users/me")).get("data") or {}
        return " · ".join(x for x in (me.get("company_name"), me.get("name")) if x)

    async def find_or_create(self, http, config, c, create):
        for term, fld in ((_digits(c.phone)[-10:], "phone"), (c.email, "email")):
            if not term:
                continue
            res = await http.request("GET", "/v1/persons/search", params={"term": term, "fields": fld, "limit": 1})
            items = ((res.get("data") or {}).get("items")) or []
            if items:
                return str(items[0]["item"]["id"])
        if not create:
            return None
        body: dict = {"name": c.name or c.phone}
        if c.phone:
            body["phone"] = [{"value": c.phone, "primary": True, "label": "mobile"}]
        if c.email:
            body["email"] = [{"value": c.email, "primary": True, "label": "work"}]
        created = await http.request("POST", "/v1/persons", json=body)
        return str(created["data"]["id"])

    async def log_call(self, http, config, external_id, call):
        m, s = divmod(int(call.duration_seconds or 0), 60)
        h, m = divmod(m, 60)
        when = (call.started_at or dt.datetime.now(UTC)).astimezone(UTC)
        await http.request("POST", "/v1/activities", json={
            "subject": f"AI call: {call.outcome_label}", "type": "call", "done": 1, "person_id": int(external_id),
            "due_date": when.strftime("%Y-%m-%d"), "due_time": when.strftime("%H:%M"),
            "duration": f"{h:02d}:{m:02d}", "note": call.note(html=True)})

    async def import_options(self, http, config):
        out = []
        try:
            flt = (await http.request("GET", "/v1/filters", params={"type": "people"})).get("data") or []
            if flt:
                out.append({"key": "filter_id", "label": "Saved filter", "type": "single",
                            "options": [{"value": str(x["id"]), "label": x.get("name") or str(x["id"])} for x in flt]})
        except CrmError:
            pass
        try:
            fields = (await http.request("GET", "/v1/personFields", params={"limit": 200})).get("data") or []
            label = next((x for x in fields if x.get("key") == "label"), None)
            if label and label.get("options"):
                out.append({"key": "label", "label": "Labels", "type": "multi",
                            "options": [{"value": str(o["id"]), "label": o.get("label") or str(o["id"])} for o in label["options"]]})
        except CrmError:
            pass
        try:
            users = (await http.request("GET", "/v1/users")).get("data") or []
            if users:
                out.append({"key": "owner", "label": "Owner", "type": "multi",
                            "options": [{"value": str(u["id"]), "label": u.get("name") or u.get("email", "")} for u in users]})
        except CrmError:
            pass
        return out

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        f = filters or {}
        want_label, want_owner = set(f.get("label") or []), set(f.get("owner") or [])
        fid = (f.get("filter_id") or [""])[0] if isinstance(f.get("filter_id"), list) else f.get("filter_id")
        out: list[Contact] = []
        start, pages = 0, 0
        while len(out) < limit and pages < 40:
            params: dict = {"start": start, "limit": 100, "sort": "add_time DESC"}
            if fid:
                params["filter_id"] = fid
            page = await http.request("GET", "/v1/persons", params=params)
            pages += 1
            rows = page.get("data") or []
            stop = False
            for p in rows:
                created = _parse_time(p.get("add_time"))
                if since and created and created <= since:
                    stop = True
                    break
                labels = {str(x) for x in (p.get("label_ids") or ([p["label"]] if p.get("label") else []))}
                if want_label and not want_label & labels:
                    continue
                owner = p.get("owner_id")
                owner = str(owner.get("id") if isinstance(owner, dict) else owner or "")
                if want_owner and owner not in want_owner:
                    continue
                phones = [x.get("value") for x in p.get("phone") or [] if x.get("value")]
                if not phones:
                    continue
                emails = [x.get("value") for x in p.get("email") or [] if x.get("value")]
                org = p.get("org_name") or ((p.get("org_id") or {}).get("name") if isinstance(p.get("org_id"), dict) else "")
                done = p.get("done_activities_count")
                out.append(Contact(p.get("name") or "", phones[0], (emails or [""])[0], org or "", str(p["id"]), created,
                                   contacted=(done > 0) if isinstance(done, int) else None))
            more = ((page.get("additional_data") or {}).get("pagination") or {}).get("more_items_in_collection")
            if stop or not more:
                break
            start += 100
        return out[:limit]


# ── HighLevel (GoHighLevel / LeadConnector) ──────────────────────────────────


class HighLevel(Provider):
    key, name = "highlevel", "GoHighLevel"
    description = "Upsert contacts, add call notes, import contacts and auto-call new ones in a sub-account."
    auth_fields = [
        AuthField("api_key", "Private integration token", placeholder="pit-…",
                  help="Sub-account → Settings → Private Integrations. Scopes: contacts read/write, locations read."),
        AuthField("location_id", "Location (sub-account) ID", secret=False, help="Settings → Business Profile → Location ID."),
    ]
    nango_providers = ("highlevel", "highlevel-white-label")
    docs_url = "https://highlevel.stoplight.io/docs/integrations"

    def nango_headers(self):
        return {"Version": "2021-07-28"}

    def native_http(self, secret, config):
        return NativeHttp("https://services.leadconnectorhq.com",
                          headers={"Authorization": f"Bearer {secret}", "Version": "2021-07-28"})

    def _loc(self, config) -> str:
        loc = (config.get("location_id") or "").strip()
        if not loc:
            raise CrmError("Add the HighLevel location ID.")
        return loc

    async def verify(self, http, config):
        loc = await http.request("GET", f"/locations/{self._loc(config)}")
        return ((loc.get("location") or {}).get("name") or "HighLevel location").strip()

    async def find_or_create(self, http, config, c, create):
        loc = self._loc(config)
        if not create:
            res = await http.request("GET", "/contacts/", params={"locationId": loc, "query": c.phone or c.email, "limit": 1})
            rows = res.get("contacts") or []
            return str(rows[0]["id"]) if rows else None
        first, last = split_name(c.name)
        body = {k: v for k, v in {"locationId": loc, "firstName": first, "lastName": last, "phone": c.phone,
                                  "email": c.email, "companyName": c.company, "source": "BlackSync AI"}.items() if v}
        res = await http.request("POST", "/contacts/upsert", json=body)
        return str((res.get("contact") or {})["id"])

    async def log_call(self, http, config, external_id, call):
        await http.request("POST", f"/contacts/{external_id}/notes", json={"body": call.note()})
        tag = {"meeting_booked": "ai-meeting-booked", "interested": "ai-interested", "callback": "ai-callback",
               "not_interested": "ai-not-interested"}.get(call.outcome)
        if tag:
            try:
                await http.request("POST", f"/contacts/{external_id}/tags", json={"tags": [tag]})
            except CrmError:
                pass

    async def import_options(self, http, config):
        try:
            tags = (await http.request("GET", f"/locations/{self._loc(config)}/tags")).get("tags") or []
        except CrmError:
            return []
        return [{"key": "tags", "label": "Tags", "type": "multi", "free": True,
                 "options": [{"value": t["name"], "label": t["name"]} for t in tags if t.get("name")]}]

    async def mark_dnc(self, http, config, external_id):
        await http.request("PUT", f"/contacts/{external_id}", json={"dnd": True})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        want_tags = {t.lower() for t in (filters or {}).get("tags") or []}
        out: list[Contact] = []
        params: dict = {"locationId": self._loc(config), "limit": 100}
        pages = 0
        while len(out) < limit and pages < 40:
            page = await http.request("GET", "/contacts/", params=params)
            pages += 1
            rows = page.get("contacts") or []
            for p in rows:
                created = _parse_time(p.get("dateAdded"))
                if since and created and created <= since:
                    continue
                tags = [t for t in p.get("tags") or [] if isinstance(t, str)]
                if want_tags and not want_tags & {t.lower() for t in tags}:
                    continue
                if not p.get("phone"):
                    continue
                dnd = bool(p.get("dnd")) or str(((p.get("dndSettings") or {}).get("Call") or {}).get("status", "")).lower() == "active"
                name = p.get("contactName") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x)
                out.append(Contact(name or "", p["phone"], p.get("email") or "", p.get("companyName") or "", str(p["id"]),
                                   created, tags=tags, dnc=dnd or bool(_DNC_TAGS & {t.lower() for t in tags})))
            meta = page.get("meta") or {}
            if len(rows) < 100 or not meta.get("startAfterId"):
                break
            params = {**params, "startAfterId": meta["startAfterId"], "startAfter": meta.get("startAfter")}
        return out[:limit]


# ── Attio ─────────────────────────────────────────────────────────────────────


class Attio(Provider):
    key, name = "attio", "Attio"
    description = "Create people, add call notes to their record, and import people to call."
    auth_fields = [AuthField("api_key", "API key", help="Attio → Workspace settings → Developers → New access token.")]
    nango_providers = ("attio",)
    docs_url = "https://developers.attio.com"

    def native_http(self, secret, config):
        return NativeHttp("https://api.attio.com", headers={"Authorization": f"Bearer {secret}"})

    async def verify(self, http, config):
        me = await http.request("GET", "/v2/self")
        return me.get("workspace_name") or "Attio workspace"

    async def find_or_create(self, http, config, c, create):
        if c.email:
            res = await http.request("POST", "/v2/objects/people/records/query",
                                     json={"filter": {"email_addresses": c.email}, "limit": 1})
            if res.get("data"):
                return res["data"][0]["id"]["record_id"]
        if c.phone:
            res = await http.request("POST", "/v2/objects/people/records/query",
                                     json={"filter": {"phone_numbers": c.phone}, "limit": 1})
            if res.get("data"):
                return res["data"][0]["id"]["record_id"]
        if not create:
            return None
        first, last = split_name(c.name)
        values: dict = {"name": [{"first_name": first, "last_name": last, "full_name": c.name or c.phone}]}
        if c.phone:
            values["phone_numbers"] = [{"original_phone_number": c.phone}]
        if c.email:
            values["email_addresses"] = [c.email]
        res = await http.request("POST", "/v2/objects/people/records", json={"data": {"values": values}})
        return res["data"]["id"]["record_id"]

    async def log_call(self, http, config, external_id, call):
        await http.request("POST", "/v2/notes", json={"data": {
            "parent_object": "people", "parent_record_id": external_id, "title": f"AI call: {call.outcome_label}",
            "format": "plaintext", "content": call.note()}})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        out: list[Contact] = []
        offset = 0
        while len(out) < limit:
            body: dict = {"limit": 100, "offset": offset, "sorts": [{"attribute": "created_at", "direction": "desc"}]}
            page = await http.request("POST", "/v2/objects/people/records/query", json=body)
            rows = page.get("data") or []
            stop = False
            for r in rows:
                v = r.get("values") or {}
                created = _parse_time(r.get("created_at"))
                if since and created and created <= since:
                    stop = True
                    break
                phones = [x.get("phone_number") or x.get("original_phone_number") for x in v.get("phone_numbers") or []]
                phones = [p for p in phones if p]
                if not phones:
                    continue
                names = v.get("name") or [{}]
                emails = [x.get("email_address") for x in v.get("email_addresses") or [] if x.get("email_address")]
                out.append(Contact(names[0].get("full_name") or "", phones[0], (emails or [""])[0], "",
                                   r["id"]["record_id"], created))
            if stop or len(rows) < 100:
                break
            offset += 100
        return out[:limit]


# ── Salesforce (OAuth via Nango) ──────────────────────────────────────────────


class Salesforce(Provider):
    key, name = "salesforce", "Salesforce"
    description = "Log AI calls as completed tasks on the lead or contact, create leads and import leads to call."
    nango_providers = ("salesforce", "salesforce-sandbox")
    native = False
    docs_url = "https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/"
    _v = "/services/data/v60.0"

    async def verify(self, http, config):
        res = await http.request("GET", f"{self._v}/query", params={"q": "SELECT Name FROM Organization LIMIT 1"})
        rows = res.get("records") or []
        return rows[0].get("Name") if rows else "Salesforce org"

    async def find_or_create(self, http, config, c, create):
        if c.phone:
            q = "FIND {" + _digits(c.phone)[-10:] + "} IN PHONE FIELDS RETURNING Contact(Id), Lead(Id) LIMIT 1"
            res = await http.request("GET", f"{self._v}/search", params={"q": q})
            hits = res.get("searchRecords") or []
            if hits:
                return hits[0]["Id"]
        if c.email:
            safe = c.email.replace("'", "")
            res = await http.request("GET", f"{self._v}/query", params={"q": f"SELECT Id FROM Lead WHERE Email = '{safe}' LIMIT 1"})
            if res.get("records"):
                return res["records"][0]["Id"]
        if not create:
            return None
        first, last = split_name(c.name)
        res = await http.request("POST", f"{self._v}/sobjects/Lead", json={
            "FirstName": first, "LastName": last or c.name or c.phone or "Unknown", "Company": c.company or "Unknown",
            "Phone": c.phone, "Email": c.email or None, "LeadSource": "BlackSync AI"})
        return res["id"]

    async def log_call(self, http, config, external_id, call):
        when = (call.started_at or dt.datetime.now(UTC)).astimezone(UTC)
        await http.request("POST", f"{self._v}/sobjects/Task", json={
            "WhoId": external_id, "Subject": f"AI call: {call.outcome_label}", "Description": call.note()[:32000],
            "Status": "Completed", "TaskSubtype": "Call", "CallType": "Outbound",
            "CallDurationInSeconds": int(call.duration_seconds or 0), "ActivityDate": when.strftime("%Y-%m-%d")})

    async def import_options(self, http, config):
        out = []
        for fld, label in (("Status", "Lead status"), ("LeadSource", "Lead source")):
            try:
                res = await http.request("GET", f"{self._v}/query",
                                         params={"q": f"SELECT {fld} v, COUNT(Id) n FROM Lead WHERE IsConverted = false GROUP BY {fld}"})
                opts = [{"value": r["v"], "label": f"{r['v']} ({r['n']})"} for r in res.get("records") or [] if r.get("v")]
                if opts:
                    out.append({"key": fld, "label": label, "type": "multi", "options": opts})
            except CrmError:
                pass
        return out

    async def mark_dnc(self, http, config, external_id):
        obj = "Lead" if str(external_id).startswith("00Q") else "Contact"
        await http.request("PATCH", f"{self._v}/sobjects/{obj}/{external_id}", json={"DoNotCall": True})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        f = filters or {}

        def quote(v: str) -> str:
            return "'" + str(v).replace("\\", "").replace("'", "\\'") + "'"

        where = ["Phone != null", "IsConverted = false"]
        for fld in ("Status", "LeadSource"):
            if f.get(fld):
                where.append(f"{fld} IN (" + ", ".join(quote(v) for v in f[fld]) + ")")
        if f.get("skip_contacted"):
            where.append("LastActivityDate = null")
        if since:
            where.append(f"CreatedDate > {since.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        q = ("SELECT Id, Name, Phone, Email, Company, CreatedDate, Status, DoNotCall, LastActivityDate FROM Lead WHERE "
             + " AND ".join(where) + f" ORDER BY CreatedDate DESC LIMIT {int(limit)}")
        res = await http.request("GET", f"{self._v}/query", params={"q": q})
        return [Contact(r.get("Name") or "", r["Phone"], r.get("Email") or "", r.get("Company") or "", r["Id"],
                        _parse_time(r.get("CreatedDate")), stage=r.get("Status") or "", dnc=bool(r.get("DoNotCall")),
                        contacted=bool(r.get("LastActivityDate"))) for r in res.get("records") or []]


# ── Zoho CRM (OAuth via Nango) ────────────────────────────────────────────────


class ZohoCrm(Provider):
    key, name = "zoho", "Zoho CRM"
    description = "Log AI calls as notes on the lead, create leads and import leads to call."
    nango_providers = ("zoho-crm",)
    native = False

    async def verify(self, http, config):
        res = await http.request("GET", "/crm/v6/org")
        org = (res.get("org") or [{}])[0]
        return org.get("company_name") or "Zoho CRM"

    async def find_or_create(self, http, config, c, create):
        if c.phone:
            res = await http.request("GET", "/crm/v6/Leads/search", params={"phone": c.phone})
            if res.get("data"):
                return str(res["data"][0]["id"])
        if not create:
            return None
        first, last = split_name(c.name)
        res = await http.request("POST", "/crm/v6/Leads", json={"data": [{
            "First_Name": first, "Last_Name": last or c.name or c.phone, "Phone": c.phone, "Email": c.email or None,
            "Company": c.company or None, "Lead_Source": "BlackSync AI"}]})
        return str(res["data"][0]["details"]["id"])

    async def log_call(self, http, config, external_id, call):
        await http.request("POST", f"/crm/v6/Leads/{external_id}/Notes", json={"data": [{
            "Note_Title": f"AI call: {call.outcome_label}", "Note_Content": call.note()}]})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        res = await http.request("GET", "/crm/v6/Leads", params={
            "fields": "Full_Name,Phone,Mobile,Email,Company,Created_Time", "per_page": min(200, limit),
            "sort_by": "Created_Time", "sort_order": "desc"})
        out = []
        for r in res.get("data") or []:
            created = _parse_time(r.get("Created_Time"))
            phone = r.get("Phone") or r.get("Mobile")
            if not phone or (since and created and created <= since):
                continue
            out.append(Contact(r.get("Full_Name") or "", phone, r.get("Email") or "", r.get("Company") or "", str(r["id"]), created))
        return out


# ── Slack (incoming webhook) ──────────────────────────────────────────────────


class Slack(Provider):
    key, name = "slack", "Slack"
    category = "notify"
    description = "Post a message to a channel when a call finishes — summary, outcome and a link."
    auth_fields = [AuthField("api_key", "Incoming webhook URL", placeholder="https://hooks.slack.com/services/…",
                             help="api.slack.com/apps → your app → Incoming Webhooks → Add New Webhook.")]
    can_import = False
    can_new_leads = False

    def native_http(self, secret, config):
        if not secret.startswith("https://hooks.slack.com/"):
            raise CrmError("Use a Slack incoming webhook URL (https://hooks.slack.com/…).")
        return NativeHttp(secret)

    async def verify(self, http, config):
        await http.request("POST", "", json={"text": "BlackSync is connected. Call results will post here."})
        return "Incoming webhook"

    async def find_or_create(self, http, config, c, create):
        return "slack"

    async def log_call(self, http, config, external_id, call):
        emoji = {"meeting_booked": ":calendar:", "interested": ":fire:", "callback": ":telephone_receiver:"}.get(call.outcome, ":phone:")
        await http.request("POST", "", json={"text": f"{emoji} {call.note()}"})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        return []


# ── Google Sheets (OAuth via Nango) ───────────────────────────────────────────


class GoogleSheets(Provider):
    key, name = "google_sheets", "Google Sheets"
    category = "sheet"
    description = "Append a row for every call, and import contacts from a sheet (needs a Phone column)."
    nango_providers = ("google-sheet",)
    native = False
    can_new_leads = False
    auth_fields = [AuthField("spreadsheet", "Spreadsheet URL", secret=False,
                             help="Paste the sheet's URL. Call rows go to a tab named “BlackSync calls”.")]

    @staticmethod
    def _sheet_id(config) -> str:
        raw = (config.get("spreadsheet") or "").strip()
        if "/d/" in raw:
            raw = raw.split("/d/", 1)[1].split("/", 1)[0]
        if not raw:
            raise CrmError("Add the spreadsheet URL.")
        return raw

    async def verify(self, http, config):
        res = await http.request("GET", f"/v4/spreadsheets/{self._sheet_id(config)}", params={"fields": "properties.title"})
        return (res.get("properties") or {}).get("title") or "Spreadsheet"

    async def find_or_create(self, http, config, c, create):
        return "sheet"

    async def log_call(self, http, config, external_id, call):
        sid = self._sheet_id(config)
        tab = "BlackSync calls"
        row = [(call.started_at or dt.datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%d %H:%M"), call.phone,
               call.outcome_label, int(call.duration_seconds or 0), call.agent_name, call.meeting_time, call.summary, call.url]
        try:
            await http.request("POST", f"/v4/spreadsheets/{sid}/values/'{tab}'!A1:append",
                               params={"valueInputOption": "USER_ENTERED"}, json={"values": [row]})
        except CrmError as exc:
            if exc.status != 400:
                raise
            await http.request("POST", f"/v4/spreadsheets/{sid}:batchUpdate",
                               json={"requests": [{"addSheet": {"properties": {"title": tab}}}]})
            header = ["Time (UTC)", "Phone", "Outcome", "Seconds", "Agent", "Meeting", "Summary", "Link"]
            await http.request("POST", f"/v4/spreadsheets/{sid}/values/'{tab}'!A1:append",
                               params={"valueInputOption": "USER_ENTERED"}, json={"values": [header, row]})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        res = await http.request("GET", f"/v4/spreadsheets/{self._sheet_id(config)}/values/A1:Z{limit + 1}")
        rows = res.get("values") or []
        if not rows:
            return []
        head = [str(h).strip().lower() for h in rows[0]]

        def col(*names):
            return next((i for i, h in enumerate(head) if h in names), None)

        ip, iname, ie, ic = col("phone", "phone number", "mobile", "cell"), col("name", "full name"), col("email"), col("company")
        if ip is None:
            raise CrmError("The sheet needs a Phone column in the first row.")
        out = []
        for i, r in enumerate(rows[1:], start=2):
            get = lambda j: (str(r[j]).strip() if j is not None and j < len(r) else "")  # noqa: E731
            if get(ip):
                out.append(Contact(get(iname), get(ip), get(ie), get(ic), f"row{i}"))
        return out


PROVIDERS: dict[str, Provider] = {p.key: p for p in (
    FollowUpBoss(), Close(), HubSpot(), HighLevel(), Pipedrive(), Salesforce(), ZohoCrm(), Attio(), GoogleSheets(), Slack(),
)}


def provider_for_nango(nango_provider: str) -> Provider | None:
    return next((p for p in PROVIDERS.values() if nango_provider in p.nango_providers), None)


def phone_key(phone: str) -> str:
    """Comparable form of a phone number (E.164)."""
    return normalize_phone(phone)
