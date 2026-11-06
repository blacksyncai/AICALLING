"""TEMPORARY read-only probe: log the inbound SIP setup (no secrets). Remove after one deploy."""
import structlog

log = structlog.get_logger(__name__)


async def probe() -> None:
    try:
        from livekit import api
        from app.services.inbound import _lk
        lk = _lk()
        try:
            for t in (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items:
                log.info("probe_in_trunk", id=t.sip_trunk_id, name=t.name, numbers=len(t.numbers),
                         sample=list(t.numbers)[:3], allowed=list(t.allowed_addresses)[:10],
                         allowed_numbers=len(t.allowed_numbers), auth=bool(t.auth_username))
            for r in (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items:
                log.info("probe_rule", id=r.sip_dispatch_rule_id, name=r.name, trunks=list(r.trunk_ids),
                         agents=[a.agent_name for a in r.room_config.agents], kind=r.rule.WhichOneof("rule"))
            for t in (await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())).items:
                log.info("probe_out_trunk", id=t.sip_trunk_id, name=t.name, address=t.address)
        finally:
            await lk.aclose()
    except Exception as exc:
        log.warning("probe_lk_failed", error=str(exc)[:300])
    try:
        from app.services import plivo
        apps = await plivo._request("GET", "Application/", params={"limit": 20})
        for a in apps.get("objects", []):
            log.info("probe_plivo_app", app_id=a.get("app_id"), name=a.get("app_name"), answer=a.get("answer_url"),
                     default=a.get("default_app"))
        nums = await plivo._request("GET", "Number/", params={"limit": 5})
        for n in nums.get("objects", []):
            log.info("probe_plivo_num", number=n.get("number"), app=n.get("application"), voice=n.get("voice_enabled"))
        try:
            trunks = await plivo._request("GET", "Zentrunk/Trunk/")
            log.info("probe_zentrunk", trunks=[(t.get("name"), t.get("trunk_direction"), t.get("trunk_id")) for t in trunks.get("objects", [])])
        except Exception as exc:
            log.info("probe_zentrunk_failed", error=str(exc)[:200])
    except Exception as exc:
        log.warning("probe_plivo_failed", error=str(exc)[:300])
