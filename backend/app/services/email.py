"""
Transactional email via Resend (https://resend.com). Optional: without
RESEND_API_KEY nothing is sent and callers fall back to shareable links.
"""

from __future__ import annotations

import html

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)


def email_enabled() -> bool:
    return bool(settings.resend_api_key)


async def send_email(to: str, subject: str, html_body: str, sender: str | None = None, kind: str = "other", idempotency_key: str | None = None) -> bool:
    if not email_enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}",
                         **({"Idempotency-Key": idempotency_key} if idempotency_key else {})},
                json={"from": sender or settings.email_from, "to": [to], "subject": subject, "html": html_body},
            )
        if resp.status_code >= 400:
            log.warning("email_send_failed", status=resp.status_code, body=resp.text[:200])
            return False
    except Exception as exc:
        log.warning("email_send_error", error=str(exc))
        return False
    try:
        resend_id = (resp.json() or {}).get("id")
    except Exception:
        resend_id = None
    if resend_id:
        await _record(resend_id, to, subject, kind)
    return True


async def _record(resend_id: str, to: str, subject: str, kind: str) -> None:
    """Remember the message so Resend's delivered / opened / clicked events can be matched to it."""
    from app.database import AsyncSessionLocal
    from app.models.email_message import EmailMessage

    try:
        async with AsyncSessionLocal() as db:
            db.add(EmailMessage(resend_id=resend_id, to_email=to.strip().lower()[:320], subject=subject[:300],
                                kind=kind[:32]))
            await db.commit()
    except Exception as exc:  # tracking must never break sending
        log.warning("email_record_failed", error=str(exc)[:200])


async def send_invite_email(to: str, org_name: str, inviter: str, link: str) -> bool:
    from app.services import email_templates as t

    org, who, href = html.escape(org_name), html.escape(inviter), html.escape(link, quote=True)
    body = t.layout(
        title=f"Join {org} on BlackSync",
        preheader=f"{who} invited you to {org}'s workspace on BlackSync.",
        heading=f"Join {org} on BlackSync",
        body_html=t.p(f"<strong style=\"color:{t.INK};\">{who}</strong> invited you to {org}'s workspace, where AI voice "
                      "agents call, qualify and book meetings with your leads.")
        + t.button(href, "Accept invite") + t.link_fallback(href) + t.divider()
        + t.p("This invite expires in 7 days. Not expecting it? You can ignore this email.", size=12, margin="0"),
    )
    return await send_email(to, f"{inviter} invited you to {org_name} on BlackSync", body,
                            sender=settings.email_from_invites or None, kind="team_invite")
