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

import re

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
        return self.outcome not in ("no_answer", "failed", "voicemail", "screened") and self.duration_seconds > 0

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
    "screened": "Call screener answered",
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


def _stage_index(pipeline: dict, stage_id: str) -> int:
    return next((i for i, st in enumerate(pipeline.get("stages") or []) if st["id"] == stage_id), -1)


def _stage_label(pipeline: dict, stage_id: str) -> str:
    return next((st["label"] for st in pipeline.get("stages") or [] if st["id"] == stage_id), stage_id)


def _should_move(pipeline: dict, current: str | None, target: str, forward_only: bool) -> bool:
    """Never touch closed (won/lost) deals; with forward_only, never move a deal back down the board."""
    if not current:
        return True
    if current == target:
        return False
    cur = next((st for st in pipeline.get("stages") or [] if st["id"] == current), None)
    if cur and cur.get("kind") in ("won", "lost"):
        return False
    return not forward_only or _stage_index(pipeline, target) > _stage_index(pipeline, current)


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

    # Pipeline sync: each call result can move the contact's deal/opportunity to a mapped stage.
    pipeline_noun = ""  # "opportunity" / "deal" / "stage" — empty when the CRM has no pipelines

    async def pipelines(self, http: BaseHttp, config: dict) -> list[dict]:
        """[{id, name, stages: [{id, label, kind: active|won|lost}]}] in board order."""
        return []

    async def set_stage(self, http: BaseHttp, config: dict, external_id: str, pipeline: dict, stage_id: str,
                        *, create: bool, forward_only: bool, name: str = "") -> str | None:
        """Move the contact's deal in `pipeline` to `stage_id`. Returns what happened, or None if nothing changed."""
        return None

    # BlackSync pipeline inside the CRM: drag a card into the queue stage and the agent calls them.
    can_install = False
    install_style = "pipeline"  # "pipeline" (stages on a board) or "tags" (tag a person to queue them)

    can_activity = False

    # Script variables: the CRM fields we can fill {{variables}} from, and one contact's values.
    can_map_fields = False

    async def field_catalog(self, http: BaseHttp, config: dict) -> list[dict]:
        """[{key, label}] of fields a contact can have (standard + the account's custom fields)."""
        return []

    async def person_fields(self, http: BaseHttp, config: dict, external_id: str) -> dict[str, str]:
        """{field key: value as text} for one contact (keys from field_catalog)."""
        return {}

    async def recent_activity(self, http: BaseHttp, config: dict, since: dt.datetime) -> list[dict]:
        """Buying signals since `since`: [{external_id, contact: Contact, kind, at}] (newest first)."""
        return []

    async def install_pipeline(self, http: BaseHttp, config: dict, name: str, stages: list[dict]) -> dict:
        """Create (or reuse, by name) a pipeline with these stages [{key, label, kind}]. Returns the pipeline
        snapshot with each stage's CRM id and its BlackSync key."""
        raise CrmError(f"{self.name} doesn't support a BlackSync pipeline yet.")

    async def queued(self, http: BaseHttp, config: dict, stage_id: str, limit: int = 10) -> list[dict]:
        """Deals waiting in a stage: [{deal_id, external_id (contact/lead), contact: Contact}]."""
        return []

    async def move_deal(self, http: BaseHttp, config: dict, deal_id: str, stage_id: str) -> None:
        return None

    async def enqueue(self, http: BaseHttp, config: dict, external_id: str, pipeline: dict, stage_id: str) -> str:
        """Put a contact into a BlackSync pipeline stage (reuse its card there, or create one). Returns the deal id."""
        raise CrmError(f"{self.name} can't queue contacts yet.")

    async def deal_stage(self, http: BaseHttp, config: dict, deal_id: str) -> str | None:
        return None

    async def context(self, http: BaseHttp, config: dict, external_id: str) -> str:
        """What the CRM knows about this contact, condensed for the agent (notes, last touches, stage)."""
        return ""

    can_scan = False

    async def scan_signals(self, http: BaseHttp, config: dict, limit: int = 1000, quick: bool = False,
                           depth: str = "", cursor: Any = None, state: dict | None = None) -> list:
        """Radar input: a radar.Signals per contact (created, inbound, calls, deals).

        depth: "quick" (newest), "recent" (recent activity) or "old" (oldest first, to dig up old leads).
        cursor/state: providers that page with a cursor read where the last batch stopped from `cursor` and
        leave the next one in state["next"], so Radar can scan the next batch."""
        return []


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

    pipeline_noun = "opportunity"

    async def pipelines(self, http, config):
        pipes = (await http.request("GET", "/v1/pipeline/")).get("data") or []
        return [{"id": p["id"], "name": p.get("name") or "Pipeline",
                 "stages": [{"id": st["id"], "label": st.get("label") or st["id"], "kind": st.get("type") or "active"}
                            for st in p.get("statuses") or [] if st.get("id")]} for p in pipes if p.get("id")]

    async def set_stage(self, http, config, external_id, pipeline, stage_id, *, create, forward_only, name=""):
        stage_ids = {st["id"] for st in pipeline.get("stages") or []}
        opps = (await http.request("GET", "/v1/opportunity/", params={
            "lead_id": external_id, "_fields": "id,status_id,date_updated", "_limit": 50})).get("data") or []
        mine = [o for o in opps if o.get("status_id") in stage_ids]
        label = _stage_label(pipeline, stage_id)
        if mine:
            opp = mine[0]
            if not _should_move(pipeline, opp.get("status_id"), stage_id, forward_only):
                return None
            await http.request("PUT", f"/v1/opportunity/{opp['id']}/", json={"status_id": stage_id})
            return f"Moved to {label}"
        if not create:
            return None
        await http.request("POST", "/v1/opportunity/", json={"lead_id": external_id, "status_id": stage_id,
                                                              "note": "Created by BlackSync AI after a call."})
        return f"Opportunity created in {label}"

    can_install = True

    async def install_pipeline(self, http, config, name, stages):
        pipes = (await http.request("GET", "/v1/pipeline/")).get("data") or []
        pipe = next((p for p in pipes if (p.get("name") or "").strip().lower() == name.strip().lower()), None)
        if pipe is None:
            pipe = await http.request("POST", "/v1/pipeline/", json={"name": name})
            pipe["statuses"] = []
        have = {(st.get("label") or "").lower(): st for st in pipe.get("statuses") or []}
        out = []
        for st in stages:
            found = have.get(st["label"].lower())
            if not found:
                found = await http.request("POST", "/v1/status/opportunity/", json={
                    "label": st["label"], "type": st.get("kind", "active"), "pipeline_id": pipe["id"]})
            out.append({"id": found["id"], "label": st["label"], "kind": st.get("kind", "active"), "key": st["key"]})
        return {"id": pipe["id"], "name": name, "stages": out}

    async def queued(self, http, config, stage_id, limit=10):
        opps = (await http.request("GET", "/v1/opportunity/", params={
            "status_id": stage_id, "_limit": limit, "_fields": "id,lead_id,contact_id"})).get("data") or []
        out = []
        for o in opps:
            if not o.get("lead_id"):
                continue
            lead = await http.request("GET", f"/v1/lead/{o['lead_id']}/", params={"_fields": ",".join(self._LEAD_FIELDS)})
            with_phone = [ct for ct in lead.get("contacts") or [] if ct.get("phones")]
            ct = next((x for x in with_phone if x.get("id") == o.get("contact_id")), None) or (with_phone[0] if with_phone else None)
            pick = None
            if ct:
                emails = [e.get("email") for e in ct.get("emails") or [] if e.get("email")]
                pick = Contact(ct.get("name") or lead.get("display_name", ""), ct["phones"][0]["phone"], (emails or [""])[0],
                               lead.get("display_name", ""), lead["id"], stage=lead.get("status_label") or "")
            out.append({"deal_id": o["id"], "external_id": o["lead_id"], "contact": pick})
        return out

    async def move_deal(self, http, config, deal_id, stage_id):
        await http.request("PUT", f"/v1/opportunity/{deal_id}/", json={"status_id": stage_id})

    async def enqueue(self, http, config, external_id, pipeline, stage_id):
        ids = {st["id"] for st in pipeline.get("stages") or []}
        opps = (await http.request("GET", "/v1/opportunity/", params={
            "lead_id": external_id, "_fields": "id,status_id", "_limit": 50})).get("data") or []
        mine = next((o for o in opps if o.get("status_id") in ids), None)
        if mine:
            if mine.get("status_id") != stage_id:
                await self.move_deal(http, config, mine["id"], stage_id)
            return mine["id"]
        created = await http.request("POST", "/v1/opportunity/", json={
            "lead_id": external_id, "status_id": stage_id, "note": "Queued by BlackSync Radar."})
        return created["id"]

    async def deal_stage(self, http, config, deal_id):
        return (await http.request("GET", f"/v1/opportunity/{deal_id}/", params={"_fields": "status_id"})).get("status_id")

    async def context(self, http, config, external_id):
        parts: list[str] = []
        try:
            lead = await http.request("GET", f"/v1/lead/{external_id}/",
                                      params={"_fields": "display_name,description,status_label,opportunities"})
        except CrmError:
            return ""
        if lead.get("status_label"):
            parts.append(f"Lead status: {lead['status_label']}.")
        for o in (lead.get("opportunities") or [])[:2]:
            parts.append(f"Opportunity: {o.get('status_label') or ''}" + (f" — {o['note']}" if o.get("note") else "") + ".")
        if lead.get("description"):
            parts.append(lead["description"].strip())
        try:
            notes = (await http.request("GET", "/v1/activity/note/", params={"lead_id": external_id, "_limit": 3})).get("data") or []
            for n in notes:
                text = (n.get("note") or "").replace("**", "").strip()
                if text:
                    parts.append(f"Note ({(n.get('date_created') or '')[:10]}): {text}")
            calls = (await http.request("GET", "/v1/activity/call/", params={"lead_id": external_id, "_limit": 3})).get("data") or []
            for c in calls:
                when = (c.get("date_created") or "")[:10]
                disp = c.get("disposition") or c.get("status") or "call"
                parts.append(f"Earlier call {when}: {disp.replace('-', ' ')}"
                             + (f", {int(c['duration'])}s" if c.get("duration") else "")
                             + (f" — {c['note'][:200]}" if c.get("note") else "") + ".")
        except CrmError:
            pass
        return "\n".join(parts)[:1500]

    can_scan = True

    async def _activities(self, http, kind: str, since: dt.datetime, cap: int) -> list[dict]:
        out, skip = [], 0
        while len(out) < cap:
            page = await http.request("GET", f"/v1/activity/{kind}/", params={
                "date_created__gte": since.strftime("%Y-%m-%dT%H:%M:%S"), "_limit": 100, "_skip": skip})
            rows = page.get("data") or []
            out += rows
            if not page.get("has_more") or not rows:
                break
            skip += 100
        return out

    async def scan_signals(self, http, config, limit=1000, quick=False, depth="", cursor=None, state=None):
        from app.services.crm.radar import Signals

        quick = quick or depth == "quick"
        now = dt.datetime.now(UTC)
        if quick:
            limit = min(limit, 300)
        leads, skip = [], 0
        while len(leads) < limit:
            page = await http.request("GET", "/v1/lead/", params={
                "_limit": 100, "_skip": skip,
                "_fields": "id,display_name,contacts,date_created,date_updated,status_label,opportunities"})
            leads += page.get("data") or []
            if not page.get("has_more"):
                break
            skip += 100
        calls = await self._activities(http, "call", now - dt.timedelta(days=180), 4000)
        inbound: dict[str, tuple[dt.datetime, str]] = {}
        for kind, label, is_in in (("email", "Emailed you", lambda a: a.get("direction") == "incoming"),
                                   ("sms", "Texted you", lambda a: a.get("direction") == "inbound"),
                                   ("form_submission", "Filled out a form", lambda a: True)):
            try:
                for a in await self._activities(http, kind, now - dt.timedelta(days=30), 1500):
                    when = _parse_time(a.get("date_created"))
                    if a.get("lead_id") and when and is_in(a) and (a["lead_id"] not in inbound or when > inbound[a["lead_id"]][0]):
                        inbound[a["lead_id"]] = (when, label)
            except CrmError:
                pass
        by_lead: dict[str, list[dict]] = {}
        for c in calls:
            if c.get("lead_id"):
                by_lead.setdefault(c["lead_id"], []).append(c)
                if c.get("direction") == "inbound":
                    when = _parse_time(c.get("date_created"))
                    if when and (c["lead_id"] not in inbound or when > inbound[c["lead_id"]][0]):
                        inbound[c["lead_id"]] = (when, "Called you")
        out = []
        for lead in leads[:limit]:
            contacts = self._contacts_of(lead)
            if not contacts:
                continue
            c0 = contacts[0]
            lc = [c for c in by_lead.get(lead["id"], []) if c.get("direction") != "inbound"]
            connected = [c for c in lc if (c.get("disposition") in ("answered", None) and (c.get("duration") or 0) >= 30)]
            last = max(lc, key=lambda c: c.get("date_created") or "") if lc else None
            opps = lead.get("opportunities") or []
            open_opps = [o for o in opps if o.get("status_type") == "active"]
            won = [o for o in opps if o.get("status_type") == "won"]
            o0 = max(open_opps, key=lambda o: o.get("date_updated") or "") if open_opps else None
            inb = inbound.get(lead["id"])
            out.append(Signals(
                external_id=lead["id"], name=c0.name, phone=c0.phone, company=lead.get("display_name", ""), email=c0.email,
                created_at=_parse_time(lead.get("date_created")), last_activity_at=_parse_time(lead.get("date_updated")),
                last_inbound_at=inb[0] if inb else None, inbound_kind=inb[1] if inb else "",
                calls=len(lc), connected_calls=len(connected),
                last_call_at=_parse_time(last.get("date_created")) if last else None,
                last_call_result=((last.get("disposition") or "").replace("-", " ").replace("vm ", "voicemail ")) if last else "",
                deal_stage=(o0 or {}).get("status_label") or "", deal_open=bool(o0),
                deal_updated_at=_parse_time((o0 or {}).get("date_updated")),
                won_at=_parse_time(max((o.get("date_won") or o.get("date_updated") or "") for o in won)) if won else None,
                status=lead.get("status_label") or "", dnc=c0.dnc))
        return out

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
            opts = [{"value": p["id"], "label": p.get("name") or "Pipeline",
                     "stages": [{"value": st["id"], "label": st.get("label") or st["id"], "kind": st.get("type") or "active"}
                                for st in p.get("statuses") or [] if st.get("id")]}
                    for p in pipes if p.get("id")]
            if opts:
                # Pick a pipeline, then any of its stages (the "opp_status" filter); no stages = the whole pipeline.
                out.insert(0, {"key": "pipeline", "label": "Pipeline", "type": "pipeline", "stage_key": "opp_status",
                               "options": opts})
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
        pipeline = (f.get("pipeline") or [""])[0] if isinstance(f.get("pipeline"), list) else (f.get("pipeline") or "")
        if pipeline and not stage_ids:
            pipes = (await http.request("GET", "/v1/pipeline/")).get("data") or []
            stage_ids = [st["id"] for p in pipes if p.get("id") == pipeline for st in p.get("statuses") or []]
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


def _fub_next(page: dict) -> tuple[str, dict] | None:
    """FUB disables deep offset paging; each page carries a nextLink to follow instead."""
    from urllib.parse import parse_qsl, urlparse

    link = ((page.get("_metadata") or {}).get("nextLink") or "").strip()
    if not link:
        return None
    u = urlparse(link)
    return u.path, dict(parse_qsl(u.query))

_FUB_OUTCOMES = {"meeting_booked": "Interested", "interested": "Interested", "callback": "Interested",
                 "not_interested": "Not Interested", "no_answer": "No Answer", "screened": "No Answer", "voicemail": "Left Message",
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
        # Plain /people (not /events): adds the contact quietly — no "New lead" texts, lead routing
        # or action plans firing on the team because of an AI call.
        person: dict = {"firstName": first or c.phone, "lastName": last, "source": "BlackSync AI"}
        if c.phone:
            person["phones"] = [{"value": c.phone}]
        if c.email:
            person["emails"] = [{"value": c.email}]
        created = await http.request("POST", "/v1/people", params={"deduplicate": "true"}, json=person)
        pid = created.get("id") or (created.get("person") or {}).get("id")
        if not pid:
            raise CrmError("Follow Up Boss didn't return the new person.")
        return str(pid)

    pipeline_noun = "stage"

    async def pipelines(self, http, config):
        stages = (await http.request("GET", "/v1/stages", params={"limit": 100})).get("stages") or []
        def kind(n: str) -> str:
            n = n.lower()
            return "won" if n in ("closed", "past client", "sphere") else "lost" if n in ("trash", "unresponsive") else "active"
        return [{"id": "stages", "name": "Lead stages",
                 "stages": [{"id": st["name"], "label": st["name"], "kind": kind(st["name"])} for st in stages if st.get("name")]}]

    async def set_stage(self, http, config, external_id, pipeline, stage_id, *, create, forward_only, name=""):
        person = await http.request("GET", f"/v1/people/{int(external_id)}", params={"fields": "id,stage"})
        if not _should_move(pipeline, person.get("stage"), stage_id, forward_only):
            return None
        await http.request("PUT", f"/v1/people/{int(external_id)}", json={"stage": stage_id})
        return f"Stage set to {stage_id}"

    can_map_fields = True
    _STANDARD = [
        ("first_name", "First name"), ("last_name", "Last name"), ("full_name", "Full name"), ("email", "Email"),
        ("phone", "Phone"), ("address", "Address (street)"), ("city", "City"), ("state", "State"), ("zip", "ZIP"),
        ("full_address", "Full address"), ("price", "Price"), ("source", "Lead source"), ("stage", "Stage"),
        ("tags", "Tags"), ("assigned_agent", "Assigned agent"), ("lender", "Assigned lender"),
        ("background", "Background"), ("created", "Date added"), ("last_activity", "Last activity"),
    ]

    @staticmethod
    def _slug(label: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")[:48]

    _cf_cache: dict = {}  # account → (fetched at, custom fields); they rarely change

    async def _custom_fields(self, http, *, fresh=False, strict=False) -> list[dict]:
        import time

        key = str(getattr(http, "basic", None) or getattr(http, "connection_id", "") or id(http))
        hit = self._cf_cache.get(key)
        if hit and not fresh and time.monotonic() - hit[0] < 600:
            return hit[1]
        try:
            from app.services.crm.automation_resources import fub_collection
            rows = await fub_collection(http, "customFields", response_key="customfields", strict_response=strict)
        except CrmError:
            if strict:
                raise
            return []
        if strict and any(not r.get("name") or not r.get("label") for r in rows):
            raise CrmError("The CRM returned incomplete custom-field definitions. Review the catalog before syncing.")
        out = [{"name": r["name"], "label": r.get("label") or r["name"],
                "type": r.get("type") or "text", "choices": r.get("choices") or []} for r in rows if r.get("name")]
        if out:
            self._cf_cache[key] = (time.monotonic(), out)
        return out

    async def field_catalog(self, http, config):
        out = [{"key": k, "label": label} for k, label in self._STANDARD]
        seen = {k for k, _ in self._STANDARD}
        for cf in await self._custom_fields(http):
            key = self._slug(cf["label"])
            if key and key not in seen:
                seen.add(key)
                out.append({"key": key, "label": f"{cf['label']} (custom)"})
        return out

    async def person_fields(self, http, config, external_id):
        p = await http.request("GET", f"/v1/people/{int(external_id)}", params={"fields": "allFields"})
        addr = next(iter(p.get("addresses") or []), {}) or {}
        money = p.get("price")
        price = (f"${int(money):,}" if isinstance(money, (int, float)) and money else str(money or ""))
        out = {
            "first_name": p.get("firstName") or "", "last_name": p.get("lastName") or "",
            "full_name": p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x),
            "email": next((e.get("value") for e in p.get("emails") or [] if e.get("value")), ""),
            "phone": next((x.get("value") for x in p.get("phones") or [] if x.get("value")), ""),
            "address": addr.get("street") or "", "city": addr.get("city") or "", "state": addr.get("state") or "",
            "zip": addr.get("code") or "",
            "full_address": ", ".join(x for x in (addr.get("street"), addr.get("city"),
                                                  " ".join(y for y in (addr.get("state"), addr.get("code")) if y)) if x),
            "price": price, "source": p.get("source") or "", "stage": p.get("stage") or "",
            "tags": ", ".join(t for t in p.get("tags") or [] if isinstance(t, str))[:300],
            "assigned_agent": p.get("assignedTo") or "", "lender": p.get("assignedLenderName") or "",
            "background": (p.get("background") or "")[:500],
            "created": (p.get("created") or "")[:10], "last_activity": (p.get("lastActivity") or "")[:10],
        }
        labels = {cf["name"]: cf["label"] for cf in await self._custom_fields(http)}
        for k, v in p.items():
            if k.startswith("custom") and k in labels and v not in (None, "", []):
                out[self._slug(labels[k])] = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
        return {k: str(v)[:500] for k, v in out.items() if v not in (None, "")}

    can_scan = True

    async def _pages(self, http, path: str, key: str, cap: int, params: dict,
                     start: tuple[str, dict] | None = None, state: dict | None = None) -> list[dict]:
        out: list[dict] = []
        req: tuple[str, dict] | None = start or (path, {**params, "limit": 100})
        while req and len(out) < cap:
            page = await http.request("GET", req[0], params=req[1])
            rows = page.get(key) or []
            out += rows
            req = _fub_next(page) if len(rows) >= 100 else None
        if state is not None:
            state["next"] = list(req) if req else None  # where the next batch starts
        return out

    _FIELDS = "id,name,firstName,lastName,phones,emails,created,updated,stage,tags,lastActivity,contacted,price,source,assignedPondId"
    # (people sort, how many people per batch, read calls?, events to read)
    _DEPTHS = {"quick": ("-created", 300, False, 300), "recent": ("-updated", 1000, True, 1500),
               "old": ("created", 300, False, 0)}

    async def scan_signals(self, http, config, limit=1000, quick=False, depth="", cursor=None, state=None):
        from app.services.crm.radar import Signals

        # quick: the newest people (who came in lately and hasn't been touched); recent: everyone active lately;
        # old: oldest first, to dig up leads from months or years ago. Each batch can be continued (cursor).
        depth = depth or ("quick" if quick else "recent")
        sort, batch, with_calls, n_events = self._DEPTHS.get(depth, self._DEPTHS["recent"])
        start = (cursor[0], dict(cursor[1])) if cursor else None
        people = await self._pages(http, "/v1/people", "people", min(batch, limit), {"sort": sort, "fields": self._FIELDS},
                                   start=start, state=state)
        calls = await self._pages(http, "/v1/calls", "calls", 3000, {"sort": "-created"}) if with_calls else []
        # FUB's lead events are the gold: website visits, property views/saves, inquiries.
        events = await self._pages(http, "/v1/events", "events", n_events, {"sort": "-created"}) if n_events else []
        ponds: dict[str, str] = {}
        if any(p.get("assignedPondId") for p in people):
            from app.services.crm.automation_resources import fub_collection
            try:
                ponds = {str(x.get("id")): x.get("name") or "" for x in await fub_collection(http, "ponds")}
            except Exception:
                pass  # pond names are a filter nicety; the scan still works without them
        by_person: dict[str, list[dict]] = {}
        for c in calls:
            if c.get("personId"):
                by_person.setdefault(str(c["personId"]), []).append(c)
        inbound: dict[str, tuple[dt.datetime, str]] = {}
        for e in events:
            pid, when = str(e.get("personId") or ""), _parse_time(e.get("created"))
            if pid and when and (pid not in inbound or when > inbound[pid][0]):
                kind = e.get("type") or "Activity"
                prop = ((e.get("property") or {}).get("street") or "") if isinstance(e.get("property"), dict) else ""
                inbound[pid] = (when, f"{kind}{(' · ' + prop) if prop else ''}")
        for c in calls:
            if c.get("isIncoming") and c.get("personId"):
                pid, when = str(c["personId"]), _parse_time(c.get("created"))
                if when and (pid not in inbound or when > inbound[pid][0]):
                    inbound[pid] = (when, "Called you")
        out = []
        for p in people[:limit]:
            phones = [x for x in p.get("phones") or [] if x.get("value")]
            if not phones:
                continue
            pid = str(p["id"])
            tags = {t.lower() for t in p.get("tags") or [] if isinstance(t, str)}
            lc = [c for c in by_person.get(pid, []) if not c.get("isIncoming")]
            connected = [c for c in lc if (c.get("duration") or 0) >= 45 or c.get("outcome") in ("Interested", "Not Interested")]
            last = max(lc, key=lambda c: c.get("created") or "") if lc else None
            stage = p.get("stage") or ""
            inb = inbound.get(pid)
            name = p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x)
            emails = [x.get("value") for x in p.get("emails") or [] if x.get("value")]
            out.append(Signals(
                external_id=pid, name=name, phone=phones[0]["value"], email=(emails or [""])[0],
                created_at=_parse_time(p.get("created")), last_activity_at=_parse_time(p.get("lastActivity") or p.get("updated")),
                last_inbound_at=inb[0] if inb else None, inbound_kind=inb[1] if inb else "",
                calls=len(lc), connected_calls=len(connected), calls_known=with_calls,
                last_call_at=_parse_time(last.get("created")) if last else None,
                last_call_result=(last.get("outcome") or "") if last else "",
                deal_stage=stage, deal_open=stage.lower() not in ("closed", "past client", "trash", "sphere"),
                deal_updated_at=None,
                won_at=_parse_time(p.get("updated")) if stage.lower() in ("closed", "past client") else None,
                status=stage, dnc=stage.lower() == "trash" or bool(_DNC_TAGS & tags),
                source=p.get("source") or "", pond=ponds.get(str(p.get("assignedPondId") or ""), ""),
                tags=[t for t in p.get("tags") or [] if isinstance(t, str)],
                contacted=bool(p.get("contacted")) if p.get("contacted") is not None else None))
        return out

    # ── Radar "open a list": everyone in one pond, lead source or stage ──
    can_segment = True
    _SEGMENT_PARAM = {"pond": "assignedPondId", "source": "source", "stage": "stage"}

    async def segment_options(self, http, config) -> dict:
        from app.services.crm.automation_resources import fub_collection

        async def names(resource, key="name"):
            try:
                rows = await fub_collection(http, resource)
            except Exception:
                return []
            return [{"value": str(r["id"]) if resource == "ponds" else str(r.get(key) or ""), "label": str(r.get(key) or "")}
                    for r in rows if r.get(key)]
        return {"pond": await names("ponds"), "source": await names("sources"), "stage": await names("stages")}

    async def segment_signals(self, http, config, kind: str, value: str, cap: int = 5000):
        """Everyone in the pond / lead source / stage (up to cap). The filter is sent to FUB and also checked
        here, so the list is right even if FUB ignores it (just slower)."""
        from app.services.crm.radar import Signals

        field = {"pond": "assignedPondId", "source": "source", "stage": "stage"}[kind]
        people = await self._pages(http, "/v1/people", "people", cap,
                                   {"sort": "-created", "fields": self._FIELDS, self._SEGMENT_PARAM[kind]: value})
        out = []
        for p in people:
            if str(p.get(field) or "") != str(value):
                continue
            phones = [x for x in p.get("phones") or [] if x.get("value")]
            if not phones:
                continue
            tags = {t.lower() for t in p.get("tags") or [] if isinstance(t, str)}
            stage = p.get("stage") or ""
            name = p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x)
            emails = [x.get("value") for x in p.get("emails") or [] if x.get("value")]
            out.append(Signals(
                external_id=str(p["id"]), name=name, phone=phones[0]["value"], email=(emails or [""])[0],
                created_at=_parse_time(p.get("created")), last_activity_at=_parse_time(p.get("lastActivity") or p.get("updated")),
                calls_known=False, deal_stage=stage, status=stage,
                dnc=stage.lower() == "trash" or bool(_DNC_TAGS & tags), source=p.get("source") or "",
                tags=[t for t in p.get("tags") or [] if isinstance(t, str)],
                contacted=bool(p.get("contacted")) if p.get("contacted") is not None else None))
        return out

    # ── BlackSync via tags: tag someone "AI Call - <agent>" and the agent calls them ──
    can_install = True
    install_style = "tags"
    _TAG_LABELS = {"calling": "AI Calling", "no_answer": "AI No Answer", "voicemail": "AI Voicemail",
                   "follow_up": "AI Talked", "booked": "AI Booked", "not_interested": "AI Not Interested",
                   "dnc": "AI Do Not Call"}

    @classmethod
    def _managed(cls, tag: str) -> bool:
        return tag in cls._TAG_LABELS.values() or tag.startswith("AI Call - ")

    async def install_pipeline(self, http, config, name, stages):
        agent = name.split("·", 1)[-1].strip() or "Agent"
        out = []
        for st in stages:
            if st.get("custom"):
                tag = st["label"]  # the user named this tag
            else:
                tag = f"AI Call - {agent}" if st["key"] == "queued" else self._TAG_LABELS.get(st["key"], f"AI {st['label']}")
            out.append({"id": tag, "label": tag, "kind": st.get("kind", "active"), "key": st["key"]})
        await http.request("GET", "/v1/me")  # the key still works
        return {"id": f"tags:{agent}", "name": f"Tags for {agent}", "stages": out}

    async def _person(self, http, pid: str, fields: str) -> dict:
        return await http.request("GET", f"/v1/people/{int(pid)}", params={"fields": fields})

    async def queued(self, http, config, stage_id, limit=10):
        page = await http.request("GET", "/v1/people", params={
            "tags": stage_id, "limit": max(limit, 25), "sort": "updated",
            "fields": "id,name,firstName,lastName,phones,emails,stage,tags"})
        out = []
        for p in page.get("people") or []:
            if stage_id not in (p.get("tags") or []):
                continue  # the tag filter wasn't applied — only take people who really carry the tag
            phones = [x["value"] for x in p.get("phones") or [] if x.get("value")]
            emails = [x.get("value") for x in p.get("emails") or [] if x.get("value")]
            name = p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x)
            c = Contact(name, phones[0], (emails or [""])[0], "", str(p["id"]), stage=p.get("stage") or "",
                        tags=p.get("tags") or []) if phones else None
            out.append({"deal_id": str(p["id"]), "external_id": str(p["id"]), "contact": c})
        return out[:limit]

    async def move_deal(self, http, config, deal_id, stage_id):
        person = await self._person(http, deal_id, "id,tags")
        tags = [t for t in person.get("tags") or [] if not self._managed(t)] + [stage_id]
        await http.request("PUT", f"/v1/people/{int(deal_id)}", json={"tags": tags})

    async def deal_stage(self, http, config, deal_id):
        tags = (await self._person(http, deal_id, "id,tags")).get("tags") or []
        return next((t for t in tags if self._managed(t)), None)

    async def enqueue(self, http, config, external_id, pipeline, stage_id):
        await self.move_deal(http, config, external_id, stage_id)
        return external_id

    async def context(self, http, config, external_id):
        parts: list[str] = []
        try:
            p = await self._person(http, external_id, "id,name,stage,source,tags,price,assignedTo,created,lastActivity")
        except CrmError:
            return ""
        bits = [f"Stage: {p['stage']}" if p.get("stage") else "", f"Source: {p['source']}" if p.get("source") else "",
                f"Price range: ${p['price']:,}" if isinstance(p.get("price"), (int, float)) and p["price"] else "",
                f"Agent: {p['assignedTo']}" if p.get("assignedTo") else "",
                f"Tags: {', '.join(t for t in (p.get('tags') or []) if not self._managed(t))}" if p.get("tags") else ""]
        parts.append(". ".join(b for b in bits if b) + ".")
        for path, key, fmt in (
            ("/v1/events", "events", lambda e: f"{(e.get('created') or '')[:10]} {e.get('type') or 'Activity'}"
             + (f": {(e.get('property') or {}).get('street')}" if isinstance(e.get("property"), dict) and (e.get("property") or {}).get("street") else "")
             + (f" — {e['message'][:160]}" if e.get("message") else "")),
            ("/v1/notes", "notes", lambda n: f"Note {(n.get('created') or '')[:10]}: {(n.get('body') or '')[:300]}"),
            ("/v1/calls", "calls", lambda c: f"Call {(c.get('created') or '')[:10]}: {c.get('outcome') or ('incoming' if c.get('isIncoming') else 'outgoing')}"
             + (f", {int(c['duration'])}s" if c.get("duration") else "") + (f" — {(c.get('note') or '')[:160]}" if c.get("note") else "")),
        ):
            try:
                rows = (await http.request("GET", path, params={"personId": int(external_id), "limit": 3, "sort": "-created"})).get(key) or []
                parts += [fmt(r) for r in rows]
            except CrmError:
                pass
        return "\n".join(x for x in parts if x.strip(". "))[:1500]

    can_activity = True
    _HOT_EVENTS = {"viewed property", "saved property", "property inquiry", "seller inquiry", "general inquiry",
                   "registration", "visited open house", "property search", "inquiry"}

    async def recent_activity(self, http, config, since):
        out, req = [], ("/v1/events", {"sort": "-created", "limit": 100})
        seen: set[str] = set()
        while req:
            page = await http.request("GET", req[0], params=req[1])
            rows = page.get("events") or []
            stop = False
            for e in rows:
                when = _parse_time(e.get("created"))
                if when and when <= since:
                    stop = True
                    break
                kind = (e.get("type") or "").strip()
                pid = str(e.get("personId") or "")
                if not pid or pid in seen or kind.lower() not in self._HOT_EVENTS:
                    continue
                seen.add(pid)
                prop = (e.get("property") or {}).get("street") if isinstance(e.get("property"), dict) else ""
                out.append({"external_id": pid, "kind": kind + (f" · {prop}" if prop else ""), "at": when})
            req = None if stop or len(rows) < 100 else _fub_next(page)
        for item in out:
            p = await self._person(http, item["external_id"], "id,name,firstName,lastName,phones,emails,stage,tags")
            phones = [x["value"] for x in p.get("phones") or [] if x.get("value")]
            tags = p.get("tags") or []
            emails = [x.get("value") for x in p.get("emails") or [] if x.get("value")]
            name = p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x)
            item["contact"] = Contact(name, phones[0], (emails or [""])[0], "", item["external_id"], stage=p.get("stage") or "",
                                      tags=tags, dnc=(p.get("stage") or "").lower() == "trash" or bool(_DNC_TAGS & {t.lower() for t in tags})) if phones else None
        return [i for i in out if i.get("contact")]

    async def log_call(self, http, config, external_id, call):
        body = {"personId": int(external_id), "phone": call.phone, "isIncoming": False,
                "duration": int(call.duration_seconds or 0), "note": call.note()}
        if call.outcome in _FUB_OUTCOMES:
            body["outcome"] = _FUB_OUTCOMES[call.outcome]
        await http.request("POST", "/v1/calls", json=body)
        if call.connected and call.summary:
            await http.request("POST", "/v1/notes", json={"personId": int(external_id),
                                                         "subject": f"AI call: {call.outcome_label}", "body": call.note()})
        # Hand the human a task when there's something to do next.
        task = {"meeting_booked": ("Prep for meeting booked by AI" + (f": {call.meeting_time}" if call.meeting_time else ""), 0),
                "callback": ("Call back: asked for a callback on an AI call", 1),
                "interested": ("Follow up: interested on an AI call", 0)}.get(call.outcome)
        if task:
            try:
                person = await self._person(http, external_id, "id,assignedUserId")
                due = (dt.datetime.now(UTC) + dt.timedelta(days=task[1])).strftime("%Y-%m-%d")
                body_t = {"personId": int(external_id), "name": task[0], "type": "Follow Up", "dueDate": due}
                if person.get("assignedUserId"):
                    body_t["assignedUserId"] = person["assignedUserId"]
                await http.request("POST", "/v1/tasks", json=body_t)
            except CrmError:
                pass

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
        pages = 0
        params: dict = {"limit": 100, "sort": "-created",
                        "fields": "id,name,firstName,lastName,phones,emails,created,stage,tags,assignedPondId,assignedUserId,contacted"}
        if len(want_stage) == 1:
            params["stage"] = next(iter(want_stage))
        if len(want_pond) == 1:
            params["assignedPondId"] = next(iter(want_pond))
        req: tuple[str, dict] | None = ("/v1/people", params)
        while req and len(out) < limit and pages < 40:
            page = await http.request("GET", req[0], params=req[1])
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
            req = _fub_next(page)
        return out[:limit]


# ── HubSpot ───────────────────────────────────────────────────────────────────


class HubSpot(Provider):
    key, name = "hubspot", "HubSpot"
    description = "Log AI calls on the contact's timeline, create contacts and import contacts to call."
    auth_fields = [AuthField("api_key", "Private app access token", placeholder="pat-na1-…",
                             help="HubSpot → Settings → Integrations → Private apps. Scopes: crm.objects.contacts.read/write "
                                  "(and crm.objects.deals.read/write to move deal stages).")]
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

    pipeline_noun = "deal"

    async def pipelines(self, http, config):
        pipes = (await http.request("GET", "/crm/v3/pipelines/deals")).get("results") or []
        out = []
        for p in pipes:
            stages = sorted(p.get("stages") or [], key=lambda st: st.get("displayOrder") or 0)
            out.append({"id": str(p["id"]), "name": p.get("label") or "Pipeline", "stages": [
                {"id": str(st["id"]), "label": st.get("label") or str(st["id"]),
                 "kind": ("won" if (st.get("metadata") or {}).get("probability") in ("1.0", 1, 1.0)
                          else "lost" if (st.get("metadata") or {}).get("probability") in ("0.0", 0, 0.0)
                          and (st.get("metadata") or {}).get("isClosed") in ("true", True) else "active")}
                for st in stages]})
        return out

    async def set_stage(self, http, config, external_id, pipeline, stage_id, *, create, forward_only, name=""):
        stage_ids = {st["id"] for st in pipeline.get("stages") or []}
        assoc = await http.request("GET", f"/crm/v4/objects/contacts/{external_id}/associations/deals", params={"limit": 50})
        deal_ids = [str(r.get("toObjectId")) for r in assoc.get("results") or [] if r.get("toObjectId")]
        label = _stage_label(pipeline, stage_id)
        if deal_ids:
            res = await http.request("POST", "/crm/v3/objects/deals/batch/read", json={
                "properties": ["dealstage", "pipeline"], "inputs": [{"id": d} for d in deal_ids[:50]]})
            mine = [d for d in res.get("results") or []
                    if (d.get("properties") or {}).get("pipeline") == pipeline["id"]
                    and (d.get("properties") or {}).get("dealstage") in stage_ids]
            if mine:
                deal = mine[0]
                if not _should_move(pipeline, deal["properties"]["dealstage"], stage_id, forward_only):
                    return None
                await http.request("PATCH", f"/crm/v3/objects/deals/{deal['id']}", json={"properties": {"dealstage": stage_id}})
                return f"Deal moved to {label}"
        if not create:
            return None
        await http.request("POST", "/crm/v3/objects/deals", json={
            "properties": {"dealname": f"{name or 'Contact'} (BlackSync AI)", "pipeline": pipeline["id"], "dealstage": stage_id},
            "associations": [{"to": {"id": external_id},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 3}]}]})
        return f"Deal created in {label}"

    can_install = True

    async def install_pipeline(self, http, config, name, stages):
        def meta(kind: str) -> dict:
            return {"probability": "1.0" if kind == "won" else "0.0" if kind == "lost" else "0.5"}

        pipes = (await http.request("GET", "/crm/v3/pipelines/deals")).get("results") or []
        pipe = next((p for p in pipes if (p.get("label") or "").strip().lower() == name.strip().lower()), None)
        if pipe is None:
            pipe = await http.request("POST", "/crm/v3/pipelines/deals", json={
                "label": name, "displayOrder": len(pipes),
                "stages": [{"label": st["label"], "displayOrder": i, "metadata": meta(st.get("kind", "active"))}
                           for i, st in enumerate(stages)]})
        have = {(st.get("label") or "").lower(): st for st in pipe.get("stages") or []}
        out = []
        for i, st in enumerate(stages):
            found = have.get(st["label"].lower())
            if not found:
                found = await http.request("POST", f"/crm/v3/pipelines/deals/{pipe['id']}/stages", json={
                    "label": st["label"], "displayOrder": i, "metadata": meta(st.get("kind", "active"))})
            out.append({"id": str(found["id"]), "label": st["label"], "kind": st.get("kind", "active"), "key": st["key"]})
        return {"id": str(pipe["id"]), "name": name, "stages": out}

    async def queued(self, http, config, stage_id, limit=10):
        res = await http.request("POST", "/crm/v3/objects/deals/search", json={
            "filterGroups": [{"filters": [{"propertyName": "dealstage", "operator": "EQ", "value": stage_id}]}],
            "properties": ["dealstage", "dealname"], "limit": limit})
        out = []
        for d in res.get("results") or []:
            assoc = await http.request("GET", f"/crm/v4/objects/deals/{d['id']}/associations/contacts", params={"limit": 1})
            cid = next((str(r.get("toObjectId")) for r in assoc.get("results") or [] if r.get("toObjectId")), None)
            if not cid:
                continue
            ct = await http.request("GET", f"/crm/v3/objects/contacts/{cid}",
                                    params={"properties": "firstname,lastname,phone,mobilephone,email,company"})
            pr = ct.get("properties") or {}
            phone = pr.get("mobilephone") or pr.get("phone") or ""
            pick = Contact(" ".join(x for x in (pr.get("firstname"), pr.get("lastname")) if x), phone, pr.get("email") or "",
                           pr.get("company") or "", cid) if phone else None
            out.append({"deal_id": str(d["id"]), "external_id": cid, "contact": pick})
        return out

    async def move_deal(self, http, config, deal_id, stage_id):
        await http.request("PATCH", f"/crm/v3/objects/deals/{deal_id}", json={"properties": {"dealstage": stage_id}})

    async def enqueue(self, http, config, external_id, pipeline, stage_id):
        await self.set_stage(http, config, external_id, pipeline, stage_id, create=True, forward_only=False)
        assoc = await http.request("GET", f"/crm/v4/objects/contacts/{external_id}/associations/deals", params={"limit": 50})
        ids = [str(r.get("toObjectId")) for r in assoc.get("results") or [] if r.get("toObjectId")]
        return ids[-1] if ids else ""

    async def deal_stage(self, http, config, deal_id):
        d = await http.request("GET", f"/crm/v3/objects/deals/{deal_id}", params={"properties": "dealstage"})
        return (d.get("properties") or {}).get("dealstage")

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

    pipeline_noun = "deal"

    async def pipelines(self, http, config):
        pipes = (await http.request("GET", "/v1/pipelines")).get("data") or []
        stages = (await http.request("GET", "/v1/stages")).get("data") or []
        out = []
        for p in pipes:
            mine = sorted([st for st in stages if st.get("pipeline_id") == p["id"]], key=lambda st: st.get("order_nr") or 0)
            out.append({"id": str(p["id"]), "name": p.get("name") or "Pipeline",
                        "stages": [{"id": str(st["id"]), "label": st.get("name") or str(st["id"]), "kind": "active"} for st in mine]})
        return out

    async def set_stage(self, http, config, external_id, pipeline, stage_id, *, create, forward_only, name=""):
        stage_ids = {st["id"] for st in pipeline.get("stages") or []}
        deals = (await http.request("GET", f"/v1/persons/{int(external_id)}/deals", params={"status": "open"})).get("data") or []
        mine = [d for d in deals if str(d.get("stage_id")) in stage_ids]
        label = _stage_label(pipeline, stage_id)
        if mine:
            deal = mine[0]
            if not _should_move(pipeline, str(deal.get("stage_id")), stage_id, forward_only):
                return None
            await http.request("PUT", f"/v1/deals/{deal['id']}", json={"stage_id": int(stage_id)})
            return f"Deal moved to {label}"
        if not create:
            return None
        await http.request("POST", "/v1/deals", json={"title": f"{name or 'Contact'} (BlackSync AI)",
                                                     "person_id": int(external_id), "stage_id": int(stage_id)})
        return f"Deal created in {label}"

    can_install = True

    async def install_pipeline(self, http, config, name, stages):
        pipes = (await http.request("GET", "/v1/pipelines")).get("data") or []
        pipe = next((p for p in pipes if (p.get("name") or "").strip().lower() == name.strip().lower()), None)
        if pipe is None:
            pipe = (await http.request("POST", "/v1/pipelines", json={"name": name})).get("data") or {}
        have = {(st.get("name") or "").lower(): st for st in (await http.request(
            "GET", "/v1/stages", params={"pipeline_id": pipe["id"]})).get("data") or []}
        out = []
        for st in stages:
            found = have.get(st["label"].lower())
            if not found:
                found = (await http.request("POST", "/v1/stages", json={"name": st["label"], "pipeline_id": pipe["id"]})).get("data") or {}
            out.append({"id": str(found["id"]), "label": st["label"], "kind": st.get("kind", "active"), "key": st["key"]})
        return {"id": str(pipe["id"]), "name": name, "stages": out}

    async def queued(self, http, config, stage_id, limit=10):
        deals = (await http.request("GET", "/v1/deals", params={"stage_id": int(stage_id), "status": "open", "limit": limit})).get("data") or []
        out = []
        for d in deals:
            pid = d.get("person_id")
            pid = pid.get("value") if isinstance(pid, dict) else pid
            if not pid:
                continue
            person = (await http.request("GET", f"/v1/persons/{int(pid)}")).get("data") or {}
            phones = [x.get("value") for x in person.get("phone") or [] if x.get("value")]
            emails = [x.get("value") for x in person.get("email") or [] if x.get("value")]
            pick = Contact(person.get("name") or "", phones[0], (emails or [""])[0], person.get("org_name") or "", str(pid)) if phones else None
            out.append({"deal_id": str(d["id"]), "external_id": str(pid), "contact": pick})
        return out

    async def move_deal(self, http, config, deal_id, stage_id):
        await http.request("PUT", f"/v1/deals/{int(deal_id)}", json={"stage_id": int(stage_id)})

    async def enqueue(self, http, config, external_id, pipeline, stage_id):
        ids = {st["id"] for st in pipeline.get("stages") or []}
        deals = (await http.request("GET", f"/v1/persons/{int(external_id)}/deals", params={"status": "open"})).get("data") or []
        mine = next((d for d in deals if str(d.get("stage_id")) in ids), None)
        if mine:
            if str(mine.get("stage_id")) != stage_id:
                await self.move_deal(http, config, str(mine["id"]), stage_id)
            return str(mine["id"])
        created = (await http.request("POST", "/v1/deals", json={"title": "BlackSync AI call", "person_id": int(external_id),
                                                               "stage_id": int(stage_id)})).get("data") or {}
        return str(created["id"])

    async def deal_stage(self, http, config, deal_id):
        d = (await http.request("GET", f"/v1/deals/{int(deal_id)}")).get("data") or {}
        return str(d.get("stage_id")) if d.get("stage_id") is not None else None

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

    pipeline_noun = "opportunity"

    async def pipelines(self, http, config):
        pipes = (await http.request("GET", "/opportunities/pipelines", params={"locationId": self._loc(config)})).get("pipelines") or []
        return [{"id": p["id"], "name": p.get("name") or "Pipeline",
                 "stages": [{"id": st["id"], "label": st.get("name") or st["id"], "kind": "active"}
                            for st in sorted(p.get("stages") or [], key=lambda st: st.get("position") or 0)]} for p in pipes]

    async def set_stage(self, http, config, external_id, pipeline, stage_id, *, create, forward_only, name=""):
        found = (await http.request("GET", "/opportunities/search", params={
            "location_id": self._loc(config), "contact_id": external_id, "pipeline_id": pipeline["id"]})).get("opportunities") or []
        label = _stage_label(pipeline, stage_id)
        if found:
            opp = found[0]
            if opp.get("status") in ("won", "lost") or not _should_move(pipeline, opp.get("pipelineStageId"), stage_id, forward_only):
                return None
            await http.request("PUT", f"/opportunities/{opp['id']}", json={"pipelineStageId": stage_id})
            return f"Moved to {label}"
        if not create:
            return None
        await http.request("POST", "/opportunities/", json={"pipelineId": pipeline["id"], "locationId": self._loc(config),
                                                            "pipelineStageId": stage_id, "contactId": external_id,
                                                            "name": f"{name or 'Contact'} (BlackSync AI)", "status": "open"})
        return f"Opportunity created in {label}"

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
    # Self-serve: the customer's admin makes a Connected App with the Client Credentials Flow and pastes these.
    auth_fields = [
        AuthField("domain", "Salesforce domain", secret=False, placeholder="acme.my.salesforce.com",
                  help="Setup → My Domain → Current My Domain URL."),
        AuthField("client_id", "Consumer Key", secret=False, placeholder="3MVG9…",
                  help="Setup → App Manager → New Connected App: enable OAuth (scope 'api') and 'Enable Client "
                       "Credentials Flow', then in Manage → Edit Policies set a Run As user. Copy the Consumer Key "
                       "and Secret from Manage Consumer Details."),
        AuthField("api_key", "Consumer Secret"),
    ]
    docs_url = "https://help.salesforce.com/s/articleView?id=sf.connected_app_client_credentials_setup.htm"
    _v = "/services/data/v60.0"

    def native_http(self, secret, config):
        from app.services.crm.http import SalesforceHttp
        from app.services.crm.salesforce_oauth import org_host

        if not (config.get("client_id") or "").strip():
            raise CrmError("Paste the Consumer Key from your Salesforce Connected App.")
        host = org_host(config.get("domain", ""))
        return SalesforceHttp({"client_id": config["client_id"].strip(), "client_secret": secret},
                              {"instance_url": f"https://{host}"})

    def http(self, secret, config):
        if config.get("sf_native"):  # our own OAuth: secret holds the token pair (JSON)
            import json as _json

            from app.services.crm.http import SalesforceHttp

            return SalesforceHttp(_json.loads(secret or "{}"), config)
        return super().http(secret, config)

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


# ── Real-estate CRMs: BoldTrail / kvCORE, Lofty, Sierra Interactive ───────────


def _digits10(phone: str) -> str:
    d = "".join(ch for ch in phone or "" if ch.isdigit())
    return d[-10:] if len(d) >= 10 else d


class BoldTrail(Provider):
    """kvCORE's public API (BoldTrail is kvCORE's new name). Notes and calls are PUT on singular /contact paths."""

    key, name = "boldtrail", "BoldTrail / kvCORE"
    description = "Log every AI call on the contact with the summary and result, create contacts and import contacts to call."
    auth_fields = [AuthField("api_key", "API token", placeholder="eyJ0eXAi…",
                             help="BoldTrail/kvCORE → Lead Engine → Lead Dropbox → My API Tokens → Generate (Contacts access).")]
    docs_url = "https://help.insiderealestate.com/en/articles/4263959-boldtrail-api-tokens"
    can_new_leads = False  # no reliable "created since" order in the public API yet

    def native_http(self, secret, config):
        return NativeHttp("https://api.kvcore.com/v2/public", headers={"Authorization": f"Bearer {secret}"})

    async def verify(self, http, config):
        res = await http.request("GET", "/contacts", params={"limit": 1})
        return f"{res.get('total', 0):,} contacts" if isinstance(res, dict) and res.get("total") is not None else "kvCORE account"

    @staticmethod
    def _contact(r: dict) -> Contact | None:
        phone = next((r.get(k) for k in ("cell_phone_1", "cell_phone_2", "home_phone", "work_phone") if r.get(k)), "")
        if not phone:
            return None
        name = r.get("name") or " ".join(x for x in (r.get("first_name"), r.get("last_name")) if x)
        return Contact(name or "", str(phone), r.get("email") or "", "", str(r.get("id")),
                       _parse_time(r.get("created_at") or r.get("date_created")),
                       stage=_KV_STATUS.get(r.get("status"), ""), dnc=r.get("phone_on") in (0, False, "0"))

    async def find_or_create(self, http, config, c, create):
        if c.email:
            res = await http.request("GET", "/contacts", params={"filter[email]": c.email, "limit": 1})
            rows = (res or {}).get("data") or []
            if rows:
                return str(rows[0]["id"])
        if not create:
            return None
        first, last = split_name(c.name)
        body = {"first_name": first or c.phone, "last_name": last, "cell_phone_1": _digits10(c.phone),
                "source": "BlackSync AI", "status": 0}
        if c.email:
            body["email"] = c.email
        res = await http.request("POST", "/contact", json=body)
        cid = (res or {}).get("id") or ((res or {}).get("data") or {}).get("id")
        return str(cid) if cid else None

    async def log_call(self, http, config, external_id, call):
        result = 3 if call.connected else 1 if call.outcome == "wrong_number" else 2  # Contacted / Bad number / Not home
        await http.request("PUT", f"/contact/{external_id}/action/call", json={
            "date": (call.started_at or dt.datetime.now(dt.timezone.utc)).isoformat(),
            "direction": "outbound", "result": result, "notes": call.note()})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        out: list[Contact] = []
        page = 1
        while len(out) < limit:
            res = await http.request("GET", "/contacts", params={"page": page, "limit": 100})
            rows = (res or {}).get("data") or []
            for r in rows:
                c = self._contact(r)
                if c and not (since and c.created_at and c.created_at <= since):
                    out.append(c)
            if not rows or page >= int((res or {}).get("last_page") or page):
                break
            page += 1
        return out[:limit]


_KV_STATUS = {0: "New", 1: "Client", 2: "Closed", 3: "Sphere", 4: "Active", 5: "Contract", 6: "Archived", 7: "Prospect"}


_LOFTY_OUTCOME = {"voicemail": "VoiceMessage", "no_answer": "NoAnswer", "failed": "NoAnswer",
                  "wrong_number": "BadNumber", "do_not_call": "DNCContact"}


class Lofty(Provider):
    key, name = "lofty", "Lofty"
    description = "Log every AI call on the lead with the summary and result, create leads, import leads and auto-call new ones."
    auth_fields = [AuthField("api_key", "API key", help="Lofty → Settings → Integrations → API → generate a key.")]
    docs_url = "https://developer.lofty.com"

    def native_http(self, secret, config):
        return NativeHttp("https://api.lofty.com", headers={"Authorization": f"token {secret}"})

    async def verify(self, http, config):
        me = await http.request("GET", "/v1.0/me")
        me = (me or {}).get("data", me) or {}
        return " ".join(x for x in (me.get("firstName"), me.get("lastName")) if x) or me.get("email") or "Lofty account"

    @staticmethod
    def _contact(r: dict) -> Contact | None:
        phones = [p for p in r.get("phones") or [] if p]
        if not phones:
            return None
        emails = [e for e in r.get("emails") or [] if e]
        name = " ".join(x for x in (r.get("firstName"), r.get("lastName")) if x)
        tags = [t.get("tagName", "") for t in r.get("tags") or [] if isinstance(t, dict)]
        return Contact(name, str(phones[0]), emails[0] if emails else "", "", str(r.get("leadId")),
                       _parse_time(r.get("createTime")), tags=[t for t in tags if t], stage=r.get("stage") or "",
                       dnc=bool(r.get("cannotCall")))

    async def _find(self, http, **params) -> str | None:
        res = await http.request("GET", "/v1.0/leads", params={**params, "limit": 1, "preciseSearchFlag": "true"})
        leads = (res or {}).get("leads") or []
        return str(leads[0]["leadId"]) if leads else None

    async def find_or_create(self, http, config, c, create):
        found = (c.email and await self._find(http, email=c.email)) or (c.phone and await self._find(http, phone=_digits10(c.phone)))
        if found or not create:
            return found or None
        first, last = split_name(c.name)
        body = {"firstName": first or c.phone, "lastName": last, "phones": [_digits10(c.phone)] if c.phone else [],
                "emails": [c.email] if c.email else [], "source": "BlackSync AI"}
        res = await http.request("POST", "/v1.0/leads", json=body)
        lid = (res or {}).get("leadId") or ((res or {}).get("data") or {}).get("leadId")
        return str(lid) if lid else None

    async def log_call(self, http, config, external_id, call):
        await http.request("POST", "/v1.0/logType", json={
            "leadId": int(external_id), "logType": "logCall", "content": call.note()[:5000],
            "leadPhoneNumber": _digits10(call.phone) or call.phone,
            "callingOutcome": "Talked" if call.connected else _LOFTY_OUTCOME.get(call.outcome or "", "NoAnswer"),
            "outboundOrInbound": "outbound", "isPin": False})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        out: list[Contact] = []
        offset = 0
        while len(out) < limit:
            res = await http.request("GET", "/v1.0/leads", params={"offset": offset, "limit": 100,
                                                                    "sort": "CreateTime", "desc": "true"})
            rows = (res or {}).get("leads") or []
            stop = False
            for r in rows:
                c = self._contact(r)
                created = _parse_time(r.get("createTime"))
                if since and created and created <= since:
                    stop = True
                    break
                if c:
                    out.append(c)
            if stop or len(rows) < 100:
                break
            offset += 100
        return out[:limit]

    can_map_fields = True

    async def field_catalog(self, http, config):
        return [{"key": k, "label": label} for k, label in (
            ("first_name", "First name"), ("last_name", "Last name"), ("full_name", "Full name"), ("email", "Email"),
            ("address", "Address (street)"), ("city", "City"), ("state", "State"), ("zip", "ZIP"),
            ("full_address", "Full address"), ("price", "Price range"), ("source", "Lead source"),
            ("stage", "Stage"), ("assigned_agent", "Assigned agent"), ("tags", "Tags"))]

    async def person_fields(self, http, config, external_id):
        res = await http.request("GET", f"/v1.0/leads/{int(external_id)}", params={"withTrash": "false"})
        p = (res or {}).get("lead") or (res or {}).get("data") or res or {}
        prop = next(iter(p.get("leadPropertyList") or []), {}) or {}
        inq = p.get("leadInquiry") or {}
        lo, hi = inq.get("priceMin"), inq.get("priceMax")
        price = (f"${int(lo):,}–${int(hi):,}" if lo and hi else f"${int(lo or hi):,}" if (lo or hi) else "")
        out = {
            "first_name": p.get("firstName") or "", "last_name": p.get("lastName") or "",
            "full_name": " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x),
            "email": next(iter(p.get("emails") or []), ""), "phone": next(iter(p.get("phones") or []), ""),
            "address": prop.get("streetAddress") or "", "city": prop.get("city") or "", "state": prop.get("state") or "",
            "zip": prop.get("zipCode") or "",
            "full_address": ", ".join(x for x in (prop.get("streetAddress"), prop.get("city"),
                                                  " ".join(y for y in (prop.get("state"), prop.get("zipCode")) if y)) if x),
            "price": price, "source": p.get("source") or p.get("leadSource") or "", "stage": p.get("stage") or "",
            "assigned_agent": p.get("assignedUser") if isinstance(p.get("assignedUser"), str) else "",
            "tags": ", ".join(t.get("tagName", "") for t in p.get("tags") or [] if isinstance(t, dict))[:300],
        }
        for a in p.get("customAttributes") or []:
            if a.get("attributeName") and a.get("value") not in (None, ""):
                out[FollowUpBoss._slug(a["attributeName"])] = str(a["value"])
        return {k: str(v)[:500] for k, v in out.items() if v not in (None, "")}


class SierraInteractive(Provider):
    key, name = "sierra", "Sierra Interactive"
    description = "Add a note with every AI call's summary and result to the lead, import leads and auto-call new ones."
    auth_fields = [AuthField("api_key", "API key",
                             help="Sierra → gear icon → Integrations → Sierra Interactive → copy the API key (admin access).")]
    docs_url = "https://api.sierrainteractivedev.com"

    def native_http(self, secret, config):
        return NativeHttp("https://api.sierrainteractivedev.com",
                          headers={"Sierra-ApiKey": secret, "Sierra-OriginatingSystemName": "BlackSync AI"})

    @staticmethod
    async def _call(http, method: str, path: str, **kw) -> Any:
        res = await http.request(method, path, **kw)
        if isinstance(res, dict) and res.get("success") is False:
            raise CrmError(res.get("errorMessage") or "The CRM refused the request.")
        return (res or {}).get("data") if isinstance(res, dict) else res

    async def verify(self, http, config):
        data = await self._call(http, "GET", "/users", params={"pageSize": 1})
        recs = (data or {}).get("records") or []
        return (recs[0].get("siteName") if recs else "") or "Sierra account"

    @staticmethod
    def _contact(r: dict) -> Contact | None:
        if not r.get("phone"):
            return None
        name = " ".join(x for x in (r.get("firstName"), r.get("lastName")) if x)
        tags = r.get("tags") or []
        return Contact(name, str(r["phone"]), r.get("email") or "", "", str(r.get("id")), _parse_time(r.get("creationDate")),
                       tags=[t if isinstance(t, str) else t.get("name", "") for t in tags], stage=r.get("leadStatus") or "",
                       dnc=str(r.get("phoneStatus") or "").lower() in ("invalid", "donotcall", "do not call"))

    async def find_or_create(self, http, config, c, create):
        for params in ({"email": c.email} if c.email else None, {"phone": _digits10(c.phone)} if c.phone else None):
            if not params:
                continue
            data = await self._call(http, "GET", "/leads/find", params={**params, "pageSize": 1})
            leads = (data or {}).get("leads") or []
            if leads:
                return str(leads[0]["id"])
        if not create or not c.email:
            return None  # Sierra can't create a lead without an email address
        import secrets

        first, last = split_name(c.name)
        data = await self._call(http, "POST", "/leads", json={
            "email": c.email, "password": secrets.token_urlsafe(12), "firstName": first or c.phone, "lastName": last,
            "phone": _digits10(c.phone), "source": "BlackSync AI", "sendRegistrationEmail": False})
        lid = (data or {}).get("leadId") or (data or {}).get("id")
        return str(lid) if lid else None

    async def log_call(self, http, config, external_id, call):
        # No call-log endpoint in Sierra's API: the call goes on the lead as a note (without pinging the agent).
        await self._call(http, "POST", f"/leads/{external_id}/note",
                         json={"message": f"AI call: {call.outcome_label}\n\n{call.note()}", "shouldNotify": False})

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        out: list[Contact] = []
        page = 1
        while len(out) < limit:
            params = {"pageNumber": page, "pageSize": 100, "sortColumn": "RegisteredDate", "sortOrder": "desc",
                      "includeTags": "true"}
            if since:
                params["leadCreationDateFrom"] = since.strftime("%m/%d/%Y")
            data = await self._call(http, "GET", "/leads/find", params=params)
            rows = (data or {}).get("leads") or []
            stop = False
            for r in rows:
                created = _parse_time(r.get("creationDate"))
                if since and created and created <= since:
                    stop = True
                    break
                c = self._contact(r)
                if c:
                    out.append(c)
            if stop or page >= int((data or {}).get("totalPages") or page):
                break
            page += 1
        return out[:limit]

    can_map_fields = True

    async def field_catalog(self, http, config):
        return [{"key": k, "label": label} for k, label in (
            ("first_name", "First name"), ("last_name", "Last name"), ("full_name", "Full name"), ("email", "Email"),
            ("address", "Address (street)"), ("city", "City"), ("state", "State"), ("zip", "ZIP"),
            ("full_address", "Full address"), ("price", "Price range"), ("source", "Lead source"),
            ("stage", "Status"), ("assigned_agent", "Assigned agent"), ("tags", "Tags"))]

    async def person_fields(self, http, config, external_id):
        p = await self._call(http, "GET", f"/leads/get/{external_id}", params={"includeTags": "true"}) or {}
        sp = p.get("searchPreference") or {}
        lo, hi = sp.get("minPrice"), sp.get("maxPrice")
        price = (f"${int(lo):,}–${int(hi):,}" if lo and hi else f"${int(lo or hi):,}" if (lo or hi) else "")
        agent = p.get("assignedTo") or {}
        out = {
            "first_name": p.get("firstName") or "", "last_name": p.get("lastName") or "",
            "full_name": " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x),
            "email": p.get("email") or "", "phone": p.get("phone") or "",
            "address": p.get("streetAddress") or "", "city": p.get("city") or "", "state": p.get("state") or "",
            "zip": p.get("zip") or "",
            "full_address": ", ".join(x for x in (p.get("streetAddress"), p.get("city"),
                                                  " ".join(y for y in (p.get("state"), p.get("zip")) if y)) if x),
            "price": price, "source": p.get("source") or "", "stage": p.get("leadStatus") or "",
            "assigned_agent": " ".join(x for x in (agent.get("agentUserFirstName"), agent.get("agentUserLastName")) if x),
            "tags": ", ".join(t if isinstance(t, str) else t.get("name", "") for t in p.get("tags") or [])[:300],
        }
        return {k: str(v)[:500] for k, v in out.items() if v not in (None, "")}


class OracleSales(Provider):
    key, name = "oracle_sales", "Oracle Sales / Fusion"
    description = "Connect Oracle Sales contacts, import people to call, and save call notes on their records."
    can_new_leads = False
    docs_url = "https://docs.oracle.com/en/cloud/saas/sales/faaps/api-contacts.html"
    auth_fields = [
        AuthField("api_key", "API user password", help="Password for your Fusion REST API user; stored encrypted."),
        AuthField("username", "API username", secret=False),
        AuthField("instance_url", "Fusion instance URL", secret=False, placeholder="https://your-instance.fa.us2.oraclecloud.com"),
    ]
    root = "/crmRestApi/resources/11.13.18.05/contacts"

    def native_http(self, secret, config):
        from urllib.parse import urlsplit
        try:
            u = urlsplit(config.get("instance_url", ""))
            port = u.port
        except ValueError:
            raise CrmError("Enter a valid Oracle Fusion instance URL.") from None
        if (u.scheme != "https" or not u.hostname or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.oraclecloud\.com", u.hostname)
                or u.username or u.password or port or u.query or u.fragment or u.path not in ("", "/")):
            raise CrmError("Enter your HTTPS Oracle Fusion instance URL, ending in .oraclecloud.com, without a path or port.")
        user = config.get("username", "").strip()
        if not user or ":" in user or any(c in user for c in "\r\n"):
            raise CrmError("Enter a valid Fusion API username.")
        return NativeHttp(f"https://{u.hostname}", basic=(user, secret))

    @staticmethod
    def _contact(r):
        phone = r.get("RawPhoneNumber") or ""
        if not phone:
            phone = "".join(str(r.get(k) or "") for k in ("PhoneCountryCode", "PhoneAreaCode", "PhoneNumber"))
        if not phone or not r.get("PartyNumber"):
            return None
        dnc = any(str(r.get(k, "")).lower() in ("true", "y", "1") for k in
                  ("DoNotCallFlag", "DoNotCallPrimaryPhoneFlag"))
        return Contact(name=r.get("ContactName") or " ".join(filter(None, [r.get("FirstName"), r.get("LastName")])),
                       phone=normalize_phone(str(phone)), email=r.get("EmailAddress") or "",
                       company=r.get("AccountName") or "", external_id=str(r["PartyNumber"]),
                       created_at=_parse_time(r.get("CreationDate")), dnc=dnc)

    async def verify(self, http, config):
        data = await http.request("GET", self.root, params={"limit": 1, "onlyData": "true"})
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise CrmError("Oracle did not return a contacts collection. Check this API user's Sales permissions.")
        return "Oracle Sales · " + config["username"]

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        out, offset = [], 0
        while len(out) < limit and offset < 10000:
            data = await http.request("GET", self.root, params={"limit": min(100, limit-len(out)), "offset": offset, "onlyData": "true"})
            rows = data.get("items") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise CrmError("Oracle returned an invalid contacts collection.")
            for row in rows:
                c = self._contact(row)
                if c and not (since and c.created_at and c.created_at <= since):
                    out.append(c)
            if not rows or not data.get("hasMore"):
                break
            offset += len(rows)
        return out[:limit]

    async def find_or_create(self, http, config, c, create):
        candidates = {}
        queries = []
        if c.email and re.fullmatch(r"[A-Za-z0-9._+@-]+", c.email):
            queries.append("EmailAddress='" + c.email + "'")
        if _digits(c.phone):
            queries.extend("RawPhoneNumber='" + value + "'" for value in dict.fromkeys([normalize_phone(c.phone), _digits(c.phone)]))
        for query in queries:
            data = await http.request("GET", self.root, params={"q": query, "limit": 100, "onlyData": "true"})
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise CrmError("Oracle returned an invalid contacts collection; no contact was created.")
            for raw in data["items"]:
                found = self._contact(raw)
                if not found and raw.get("PartyNumber") and c.email and str(raw.get("EmailAddress") or "").lower() == c.email.lower():
                    found = Contact(email=c.email, external_id=str(raw["PartyNumber"]))
                if found and ((_digits(found.phone) == _digits(c.phone) and _digits(c.phone)) or
                              (c.email and found.email.lower() == c.email.lower())):
                    candidates[found.external_id] = found
        if len(candidates) > 1:
            raise CrmError("More than one Oracle contact matches. Link the intended contact before retrying.")
        if candidates:
            return next(iter(candidates))
        if not create:
            return None
        if not c.email or not re.fullmatch(r"[A-Za-z0-9._+@-]+", c.email):
            raise CrmError("Import the existing Oracle contact first, or provide an email before creating one to reduce duplicate-contact risk.")
        first, last = split_name(c.name)
        row = await http.request("POST", self.root, json={"FirstName": first or c.phone, "LastName": last or first or c.phone,
            "ContactPoint": [{"ContactPointType": "PHONE", "PhoneNumber": c.phone}, {"ContactPointType": "EMAIL", "EmailAddress": c.email}]})
        if not isinstance(row, dict) or not row.get("PartyNumber"):
            raise CrmError("Oracle did not confirm a contact number. Review the record before retrying.")
        return str(row["PartyNumber"])

    async def log_call(self, http, config, external_id, call):
        from urllib.parse import quote
        path = self.root + "/" + quote(str(external_id), safe="")
        person = await http.request("GET", path)
        if not isinstance(person, dict) or not person.get("PartyId"):
            raise CrmError("Oracle did not return this contact's ID; no call note was written.")
        note = await http.request("POST", path + "/child/Note", json={"NoteTxt": call.note(), "NoteTypeCode": "GENERAL",
            "SourceObjectCode": "SALES_PARTY_CONTACT", "SourceObjectId": str(person["PartyId"]), "VisibilityCode": "INTERNAL"})
        if not isinstance(note, dict) or not note.get("NoteId"):
            raise CrmError("Oracle did not confirm the note. Review the contact before retrying.")

    async def mark_dnc(self, http, config, external_id):
        from urllib.parse import quote
        await http.request("PATCH", self.root + "/" + quote(str(external_id), safe=""), json={"DoNotCallFlag": True})


class RealGeeks(Provider):
    key, name = "realgeeks", "Real Geeks"
    description = "Create contacts and send call notes through the Real Geeks Incoming Leads API. Registered API access required."
    can_import = False
    can_new_leads = False
    docs_url = "https://developers.realgeeks.com/incoming-leads-api/"
    auth_fields = [
        AuthField("api_key", "Integration API password", help="Use registered Incoming Leads API credentials, not your normal Real Geeks login."),
        AuthField("username", "Integration API username", secret=False),
        AuthField("site_uuid", "Site UUID", secret=False),
        AuthField("verification_lead_id", "Existing lead UUID for connection test", secret=False, help="Read-only verification: use one existing lead on the authorized site. No test lead is created."),
    ]

    @staticmethod
    def _uuid(value):
        import uuid
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            raise CrmError("Site and lead identifiers must be valid UUIDs.") from None

    def native_http(self, secret, config):
        self._uuid(config.get("site_uuid"))
        self._uuid(config.get("verification_lead_id"))
        if not config.get("username") or ":" in config["username"] or any(c in config["username"] for c in "\r\n"):
            raise CrmError("Enter the registered integration API username.")
        return NativeHttp("https://receivers.leadrouter.realgeeks.com/rest", basic=(config["username"], secret))

    def _path(self, config, lead_id):
        return f"/sites/{self._uuid(config['site_uuid'])}/leads/{self._uuid(lead_id)}"

    async def verify(self, http, config):
        lead_id = self._uuid(config["verification_lead_id"])
        row = await http.request("GET", self._path(config, lead_id))
        if not isinstance(row, dict) or str(row.get("id", "")) != lead_id:
            raise CrmError("Real Geeks did not confirm this lead. Check the API credentials, site authorization and existing lead UUID.")
        return "Real Geeks · " + self._uuid(config["site_uuid"])

    async def find_or_create(self, http, config, c, create):
        import uuid
        if not _digits(c.phone):
            raise CrmError("A valid contact phone number is required.")
        existing = await http.request("GET", self._path(config, config["verification_lead_id"]))
        if not isinstance(existing, dict) or not existing.get("id"):
            raise CrmError("Real Geeks did not return the verification lead.")
        if c.phone and _digits(existing.get("phone", "")) == _digits(c.phone):
            return self._uuid(existing["id"])
        lead_id = str(uuid.uuid5(uuid.UUID(self._uuid(config["site_uuid"])), normalize_phone(c.phone)))
        try:
            row = await http.request("GET", self._path(config, lead_id))
            if not isinstance(row, dict) or str(row.get("id", "")) != lead_id:
                raise CrmError("Real Geeks returned a different lead. Review the linked record.")
            return lead_id
        except CrmError as exc:
            if exc.status != 404:
                raise
        if not create:
            return None
        first, last = split_name(c.name)
        body = {"id": lead_id, "source": "BlackSync", "first_name": first, "last_name": last, "phone": c.phone}
        if c.email:
            body["email"] = c.email
        await http.request("POST", f"/sites/{self._uuid(config['site_uuid'])}/leads", json=body)
        row = await http.request("GET", self._path(config, lead_id))
        if not isinstance(row, dict) or str(row.get("id", "")) != lead_id:
            raise CrmError("Real Geeks did not confirm the created lead. Review the CRM before retrying.")
        return lead_id

    async def log_call(self, http, config, external_id, call):
        await http.request("POST", self._path(config, external_id) + "/activities", json=[{"type": "note", "description": call.note()}])

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        raise CrmError("Real Geeks Incoming Leads API does not list your contacts. Existing lead imports need the separate outgoing webhook integration.")


class Brivity(Provider):
    key, name = "brivity", "Brivity"
    native = True
    can_import = True
    can_new_leads = False
    can_log_calls = False
    description = "Connect with your Brivity API token and import selected people by their Brivity person IDs. Call-note writes and full-account discovery are not supported by the published API."
    docs_url = "https://nvntd.github.io/brivity-core/doc/api/index.html"
    auth_fields = [
        AuthField("api_key", "API token", help="Use your Brivity account API token, not your login password."),
        AuthField("person_ids", "Person IDs to import (optional)", secret=False,
                  placeholder="38732871, 38732872",
                  help="Comma-separated Brivity person IDs. The published API reads individual people; it does not list or search all contacts. Update credentials to change this list."),
    ]

    @staticmethod
    def _ids(config):
        value = (config.get("person_ids") or "").strip()
        if not value:
            return []
        parts = re.split(r"[\s,]+", value)
        if len(parts) > 100 or any(not re.fullmatch(r"[1-9][0-9]{0,18}", x) for x in parts):
            raise CrmError("Enter up to 100 positive numeric Brivity person IDs, separated by commas or spaces.")
        return list(dict.fromkeys(parts))

    def native_http(self, secret, config):
        self._ids(config)
        if not secret or any(c.isspace() or c in '\"\\' for c in secret):
            raise CrmError("Enter the Brivity API token only, without an Authorization header prefix.")
        return NativeHttp("https://api.brivity.com", headers={"Authorization": f"Token token={secret}"})

    async def verify(self, http, config):
        # Read-only: connecting never creates a lead or event subscription.
        rows = await http.request("GET", "/api/v2/roster")
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get("user_id"), int) for r in rows):
            raise CrmError("Brivity did not return a valid agent roster. The API token was not verified.")
        owner = next((r for r in rows if r.get("is_owner") is True), rows[0] if rows else {})
        return str(owner.get("team") or owner.get("brokerage") or "Brivity account")

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        if since is not None or (filters or {}).get("skip_contacted"):
            raise CrmError("Brivity's published person API does not expose contact history or creation timestamps for these filters.")
        ids = self._ids(config)
        if not ids:
            raise CrmError("Add Brivity person IDs through Update credentials before importing. Full-account contact listing is not documented by Brivity.")
        people = []
        # Fail the whole preview on an inaccessible/malformed record rather than
        # silently presenting a partial import as complete. All requests are reads.
        for person_id in ids[:max(0, min(limit, 100))]:
            rows = await http.request("GET", f"/api/people/{person_id}")
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or not rows[0].get("account_id"):
                raise CrmError("Brivity did not return the requested person record.")
            row = rows[0]
            phone = normalize_phone(str(row.get("phone_number") or ""))
            if not phone:
                continue
            people.append(Contact(name=" ".join(str(row.get(k) or "") for k in ("first_name", "last_name")).strip(),
                                  phone=phone, email=str(row.get("email_address") or ""), external_id=person_id))
        return people

    async def find_or_create(self, http, config, c, create):
        raise CrmError("Brivity contact search and automatic creation are not enabled. Import existing people by their Brivity person IDs.")

    async def log_call(self, http, config, external_id, call):
        raise CrmError("Brivity call-note writes are not documented and are not enabled.")


class Apollo(Provider):
    key, name = "apollo", "Apollo"
    native = True
    can_import = True
    can_new_leads = False
    can_log_calls = False
    description = "Connect your Apollo API key to import saved contacts with phone numbers, manually or through scheduled sync. This does not search or enrich Apollo's prospect database, enroll sequences, or write call notes."
    docs_url = "https://docs.apollo.io/reference/search-for-contacts"
    auth_fields = [
        AuthField("api_key", "Apollo API key", help="Use a key with saved-contact search access. Availability depends on your Apollo plan and API permissions; never use your login password."),
        AuthField("search", "Saved-contact search (optional)", secret=False, placeholder="Name, company, title or email",
                  help="Limits imported saved contacts using Apollo's keyword search. Leave empty to import saved contacts. You can change this through Update credentials."),
    ]

    def native_http(self, secret, config):
        if not secret or secret != secret.strip() or any(ch.isspace() for ch in secret):
            raise CrmError("Enter the Apollo API key only, without spaces or a header prefix.")
        if len(str(config.get("search") or "")) > 500:
            raise CrmError("Keep the Apollo saved-contact search under 500 characters.")
        return NativeHttp("https://api.apollo.io/api/v1", headers={"X-Api-Key": secret})

    @staticmethod
    def _rows(data):
        if not isinstance(data, dict) or not isinstance(data.get("contacts"), list) or any(not isinstance(row, dict) or not row.get("id") for row in data["contacts"]):
            raise CrmError("Apollo did not return a valid saved-contact response. No contacts were imported.")
        return data["contacts"]

    async def verify(self, http, config):
        health = await http.request("GET", "/auth/health")
        if not isinstance(health, dict) or health.get("is_logged_in") is not True:
            raise CrmError("Apollo did not verify this API key.")
        # Read-only search: also verify the account/key can access saved contacts.
        self._rows(await http.request("POST", "/contacts/search", json={"page": 1, "per_page": 1}))
        return "Apollo account"

    @staticmethod
    def _contact(row):
        numbers = row.get("phone_numbers") or []
        numbers = numbers if isinstance(numbers, list) else []
        candidates = [row.get("direct_phone"), row.get("phone")]
        candidates += [number.get("sanitized_number") or number.get("raw_number") for number in numbers if isinstance(number, dict)]
        phone = next((normalized for value in candidates if isinstance(value, str) and (normalized := normalize_phone(value))), "")
        if not phone:
            return None
        labels = row.get("labels") or []
        tags = [str(label.get("name") or "") if isinstance(label, dict) else str(label) for label in labels] if isinstance(labels, list) else []
        tags += [str(label) for label in row.get("label_names", [])] if isinstance(row.get("label_names"), list) else []
        flagged = any(row.get(key) is True for key in ("do_not_call", "is_dnc", "dnc"))
        flagged = flagged or any(tag.strip().lower() in _DNC_TAGS for tag in tags)
        flagged = flagged or any(isinstance(number, dict) and (number.get("do_not_call") is True or number.get("dnc_status") in (True, "dnc", "do_not_call")) for number in numbers)
        company = row.get("organization_name") or next((value.get("name") for key in ("account", "organization") if isinstance(value := row.get(key), dict) and value.get("name")), "")
        return Contact(name=str(row.get("name") or " ".join(str(row.get(key) or "") for key in ("first_name", "last_name")).strip()),
                       phone=phone, email=str(row.get("email") or ""), company=str(company), external_id=str(row["id"]),
                       created_at=_parse_time(row.get("created_at")), tags=[tag for tag in tags if tag], dnc=flagged)

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        if since is not None or (filters or {}).get("skip_contacted"):
            raise CrmError("Apollo imports do not support new-lead timestamps or reliable previous-contact filtering. Turn off 'Skip already contacted' to import saved contacts.")
        if filters:
            raise CrmError("Unsupported Apollo import filters. Use Saved-contact search through Update credentials.")
        limit = max(0, min(int(limit), 2000))
        contacts, seen = [], set()
        for page in range(1, (limit + 99) // 100 + 1):
            per_page = 100  # Fixed page size: changing it on the last page shifts Apollo's offset.
            body = {"page": page, "per_page": per_page, "sort_by_field": "contact_created_at", "sort_ascending": False}
            if config.get("search"):
                body["q_keywords"] = str(config["search"]).strip()
            data = await http.request("POST", "/contacts/search", json=body)
            rows = self._rows(data)
            if len(rows) > per_page:
                raise CrmError("Apollo returned more saved contacts than requested. Import stopped.")
            for row in rows[:limit - (page - 1) * per_page]:
                external_id = str(row["id"])
                if external_id in seen:
                    raise CrmError("Apollo returned repeated contact IDs during pagination. Please retry the import.")
                seen.add(external_id)
                contact = self._contact(row)
                if contact:
                    contacts.append(contact)
            if len(rows) < per_page:
                break
        return contacts

    async def find_or_create(self, http, config, c, create):
        raise CrmError("Apollo contact creation and reverse lookup are not enabled by this saved-contact connector.")

    async def log_call(self, http, config, external_id, call):
        raise CrmError("Apollo call-note writes are not enabled by this saved-contact connector.")


class Rechat(Provider):
    key, name = "rechat", "Rechat"
    native = False
    can_import = False
    can_new_leads = False
    can_log_calls = False
    docs_url = "https://docs.api.rechat.com/master/user.html"
    description = "Rechat API documentation. Direct account connection is not enabled yet."
    setup_required_reason = "Rechat API documentation is linked below. Authentication and server-side contact APIs must be verified before account connection can be enabled."


class BoomTown(Provider):
    key, name = "boomtown", "BoomTown"
    native = False
    can_import = False
    can_new_leads = False
    description = "Direct account connection is awaiting verified BoomTown API documentation and provider access."
    docs_url = "https://developers.boomtownroi.com/"
    setup_required_reason = "BoomTown's API documentation is currently unavailable. This connector cannot be activated until the provider contract is verified."



PROVIDERS: dict[str, Provider] = {p.key: p for p in (
    FollowUpBoss(), Close(), HubSpot(), HighLevel(), Pipedrive(), Salesforce(), ZohoCrm(), Attio(),
    BoldTrail(), Lofty(), SierraInteractive(), OracleSales(), RealGeeks(), Brivity(), Apollo(), Rechat(), BoomTown(), GoogleSheets(), Slack(),
)}


def provider_for_nango(nango_provider: str) -> Provider | None:
    return next((p for p in PROVIDERS.values() if nango_provider in p.nango_providers), None)


def phone_key(phone: str) -> str:
    """Comparable form of a phone number (E.164)."""
    return normalize_phone(phone)


# Call results a pipeline stage can be mapped to, in the order the settings show them.
MAPPABLE_OUTCOMES = [
    ("meeting_booked", "Meeting booked"), ("interested", "Interested"), ("qualified", "Qualified"),
    ("callback", "Callback requested"), ("completed", "Talked, no clear result"), ("voicemail", "Voicemail"),
    ("no_answer", "No answer"), ("not_interested", "Not interested"), ("not_qualified", "Not qualified"),
    ("do_not_call", "Do not call"), ("wrong_number", "Wrong number"),
]

_HINTS = {
    "meeting_booked": ("booked", "discovery", "appointment", "meeting", "demo scheduled", "demo booked", "showing"),
    "interested": ("interested", "engaged", "warm", "hot", "follow up", "needs follow"),
    "qualified": ("qualified", "engaged"),
    "callback": ("follow up", "callback", "call back", "nurture"),
    "completed": ("contacted", "conversation", "attempted contact", "spoke"),
    "voicemail": ("voicemail", "voice mail", "left message", "vm"),
    "no_answer": ("dialing", "attempted", "no answer", "contact attempted", "attempting"),
    "not_interested": ("not interested", "lost", "nurture", "cold"),
    "not_qualified": ("not a fit", "not qualified", "unqualified", "disqualified", "bad fit"),
    "do_not_call": ("do not call", "dnc", "lost", "trash"),
    "wrong_number": ("bad number", "wrong number", "trash", "lost"),
}


_NEGATIVE = ("not ", "lost", "no show", "trash", "bad ", "unqualified", "disqualified", "dnc")
_POSITIVE_OUTCOMES = {"meeting_booked", "interested", "qualified", "callback", "completed"}


def suggest_mapping(pipeline: dict) -> dict[str, str]:
    """Best-guess outcome → stage map from stage names (never a won stage). The closest name wins:
    an exact match beats a prefix beats a substring, shorter labels beat longer ones."""
    stages = [st for st in pipeline.get("stages") or [] if st.get("kind") != "won"]
    out: dict[str, str] = {}
    for outcome, hints in _HINTS.items():
        pool = stages
        if outcome in _POSITIVE_OUTCOMES:
            pool = [st for st in stages if st.get("kind") != "lost" and not any(n in st["label"].lower() for n in _NEGATIVE)]
        for h in hints:
            scored = []
            for st in pool:
                lab = st["label"].lower().strip()
                if h not in lab:
                    continue
                scored.append((0 if lab == h else 1 if lab.startswith(h) else 2, len(lab), st["id"]))
            if scored:
                out[outcome] = min(scored)[2]
                break
    return out
