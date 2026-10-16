"""Send stored call transcripts as FUB notes, independently of deal routing."""
import hashlib
from html import escape

from sqlalchemy import select

from app.models.call_log import CallLog
from app.models.crm import CrmConnection, CrmTranscriptDelivery
from app.models.lead import Lead
from app.services.crm import sync
from app.services.crm.http import CrmError

PART_SIZE = 8000


def render(turns) -> str:
    """Only the spoken sides of the call; never export tool/system messages."""
    lines = []
    for turn in turns or []:
        if not isinstance(turn, dict) or turn.get("role") not in ("assistant", "user"):
            continue
        text = turn.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        speaker = "Agent" if turn["role"] == "assistant" else "Contact"
        lines.append(f"{speaker}: {text.strip()}")
    return "\n\n".join(lines)


async def send(db, conn: CrmConnection, call: CallLog, external_id: str) -> dict:
    cfg = sync.conn_settings(conn)
    if conn.provider != "followupboss" or not cfg.get("log_calls") or not cfg.get("note_transcript", True):
        return {"status": "disabled"}
    if call.org_id != conn.org_id or call.call_type not in ("outbound", "inbound"):
        raise CrmError("This call does not belong to this CRM workspace or is a browser test.")
    if not str(external_id).isdigit():
        raise CrmError("The linked FUB contact ID is invalid.")
    lead = await db.get(Lead, call.lead_id) if call.lead_id else None
    if not lead or lead.org_id != conn.org_id or str((lead.crm_refs or {}).get("followupboss") or "") != str(external_id):
        raise CrmError("Review the linked Follow Up Boss contact before sending its transcript.")
    info = sync.call_info({"call_id": str(call.id), "outcome": call.outcome, "duration_seconds": call.duration_seconds})
    if ((cfg.get("only_connected") and not info.connected)
        or call.outcome in (cfg.get("skip_outcomes") or [])
        or (call.outcome != "do_not_call" and (
            (cfg.get("only_outcomes") and call.outcome not in cfg["only_outcomes"])
            or (cfg.get("only_sentiments") and (call.sentiment or "neutral") not in cfg["only_sentiments"])
            or (call.duration_seconds or 0) < (cfg.get("min_seconds") or 0)))):
        return {"status": "filtered"}
    text = render(call.transcript)
    if not text:
        return {"status": "unavailable", "message": "No spoken transcript is stored for this call."}
    chunks = [text[i:i + PART_SIZE] for i in range(0, len(text), PART_SIZE)]
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    _, http = sync.http_for(conn)
    note_ids = []
    for index, chunk in enumerate(chunks, 1):
        # Serialize creation of receipts across normal sync and Radar workers.
        await db.execute(select(CrmConnection).where(CrmConnection.id == conn.id).with_for_update())
        receipt = (await db.execute(select(CrmTranscriptDelivery).where(
            CrmTranscriptDelivery.connection_id == conn.id, CrmTranscriptDelivery.call_id == call.id,
            CrmTranscriptDelivery.external_id == str(external_id),
            CrmTranscriptDelivery.content_hash == fingerprint, CrmTranscriptDelivery.part == str(index)))).scalar_one_or_none()
        if receipt and receipt.status == "sent":
            note_ids.append(receipt.note_id)
            continue
        if receipt and receipt.status == "pending":
            await db.commit()
            raise CrmError("A transcript note may already have reached FUB. Review the call's transcript notes before retrying; no duplicate was sent.")
        if receipt is None:
            receipt = CrmTranscriptDelivery(connection_id=conn.id, call_id=call.id,
                external_id=str(external_id), content_hash=fingerprint, part=str(index), status="pending")
            db.add(receipt)
        receipt.status = "pending"
        await db.commit()  # persist intent before the external write
        marker = f"BlackSync call {call.id} · transcript {fingerprint[:12]} · {index}/{len(chunks)}"
        link = info.url if cfg.get("note_link", True) else ""
        body = f"{marker}\nCall started: {call.started_at.isoformat()}\n\n{chunk}"
        if link:
            body += f"\n\nCall details and recording (BlackSync login required): {link}"
        try:
            response = await http.request("POST", "/v1/notes", json={"personId": int(external_id),
                "subject": f"BlackSync call transcript ({index}/{len(chunks)})", "body": escape(body).replace("\n", "<br>")})
            if not isinstance(response, dict) or not response.get("id"):
                raise CrmError("FUB did not return a transcript note receipt. Review the contact before retrying.")
        except CrmError as exc:
            if getattr(exc, "status", None) in (400, 401, 403, 404, 413, 422, 429):
                receipt.status = "rejected"
                await db.commit()
            raise
        receipt.status, receipt.note_id = "sent", str(response["id"])
        await db.commit()
        note_ids.append(receipt.note_id)
    return {"status": "sent", "parts": len(chunks), "note_ids": note_ids}
