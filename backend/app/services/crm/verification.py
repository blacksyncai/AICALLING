"""Conservative name/number evidence, never inferred from a call outcome or duration."""
import re
import unicodedata
from sqlalchemy import select
from app.models.radar_automation import RadarVerification, now
from app.services.contacts import normalize_phone


def normal(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text or "")).casefold()).strip()


def classify(transcript, expected_name: str, outcome: str = "") -> dict:
    # Only callee utterances can establish who answered. Instructions are never treated as evidence.
    tokens = re.findall(r"[^\W\d_]+", normal(expected_name), re.UNICODE)
    first = tokens[0] if tokens else ""
    if len(first) < 2 or first in {"unknown", "contact", "lead", "test", "browser"}:
        return {"status": "unverified", "evidence": []}
    name = re.compile(r"(?<!\w)" + re.escape(first) + r"(?!\w)")
    turns = [{"role": t.get("role"), "text": str(t.get("text") or t.get("content") or "")[:4000]}
             for t in (transcript or []) if isinstance(t, dict)]
    candidate = {"status": "unverified", "evidence": []}
    for i, turn in enumerate(turns):
        text = normal(turn["text"])
        if turn["role"] != "user":
            continue
        previous = turns[i - 1] if i else None
        question = normal(previous["text"]) if previous and previous["role"] == "assistant" else ""
        asks_name = bool(re.search(
            r"\b(?:am i speaking (?:with|to)|speaking (?:with|to)|is this|are you|is that|did i reach|have i reached)\s+"
            + re.escape(first) + r"(?!\w)", question))
        wrong = re.search(r"\bwrong (?:phone )?number\b|\bno (?:one|person) (?:here )?by that name\b", text)
        denies_name = asks_name and (
            re.search(r"\b(?:i(?:'m| am)|this is) not\s+" + re.escape(first) + r"(?!\w)", text) or
            re.search(r"\b(?:don't|do not) know\s+" + re.escape(first) + r"(?!\w)", text) or
            re.search(r"\b(?:this|it) (?:isn't|is not)\s+" + re.escape(first) + r"(?!\w)", text))
        if wrong or denies_name:
            return {"status": "wrong_number", "evidence": [{"turn": i, "role": "user", "text": turn["text"][:600]}]}
        voicemail = outcome == "voicemail" or bool(re.search(r"leave (?:me |a |your )?(?:message|name)|after the (?:tone|beep)|you(?:'ve| have) reached", text))
        if voicemail and name.search(text):
            candidate = {"status": "named_voicemail", "evidence": [{"turn": i, "role": "user", "text": turn["text"][:600]}]}
            continue
        if voicemail:
            continue
        self_id = name.search(text) and re.fullmatch(
            r"(?:hi[, .]*|hello[, .]*)?(?:this is|i am|i'm|it's|it is) " + re.escape(first) +
            r"(?: speaking)?[.! ,]*|" + re.escape(first) + r" speaking[.! ,]*", text)
        affirmative = asks_name and re.fullmatch(
            r"(?:yes|yeah|yep|yup|speaking|correct|that's me|that is me|this is (?:him|her)|you(?:'ve| have) got (?:him|her))"
            r"(?:[, .!]*(?:this is|i am|i'm) " + re.escape(first) + r")?[.! ,]*", text)
        if asks_name and re.fullmatch(
            r"(?:yes|yeah|yep|correct)(?:[, .!]+(?:it is|that's me|that is me))?"
            r"(?:[,.!? ]+(?:who(?:'s| is) (?:speaking|calling)|who is this))?[?.! ]*", text):
            affirmative = True
        if self_id or affirmative:
            evidence = [{"turn": i, "role": "user", "text": turn["text"][:600]}]
            if affirmative:
                evidence.insert(0, {"turn": i - 1, "role": "assistant", "text": previous["text"][:600]})
            candidate = {"status": "name_confirmed", "evidence": evidence}
    return candidate


async def record(db, call, lead):
    if not lead or call.org_id != lead.org_id or call.call_type not in ("outbound", "inbound"):
        return None
    data = classify(call.transcript, lead.name, call.outcome or "")
    row = (await db.execute(select(RadarVerification).where(RadarVerification.call_id == call.id))).scalar_one_or_none()
    if row is None:
        row = RadarVerification(org_id=call.org_id, call_id=call.id, lead_id=lead.id)
        db.add(row)
    row.phone = normalize_phone(call.to_phone or lead.phone)
    row.expected_name, row.status, row.evidence, row.analyzed_at = lead.name, data["status"], data["evidence"], now()
    await db.flush()
    return row
