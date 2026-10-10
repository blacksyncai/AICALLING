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


async def send_email(to: str, subject: str, html_body: str) -> bool:
    if not email_enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.email_from, "to": [to], "subject": subject, "html": html_body},
            )
        if resp.status_code >= 400:
            log.warning("email_send_failed", status=resp.status_code, body=resp.text[:200])
            return False
        return True
    except Exception as exc:
        log.warning("email_send_error", error=str(exc))
        return False


async def send_invite_email(to: str, org_name: str, inviter: str, link: str) -> bool:
    org, who = html.escape(org_name), html.escape(inviter)
    body = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:24px;color:#1c1917">
      <h2 style="margin:0 0 12px">Join {org} on BlackSync</h2>
      <p style="color:#57534e;line-height:1.5">{who} invited you to {org}'s workspace, where AI voice agents
      call, qualify and book meetings with your leads.</p>
      <p style="margin:24px 0"><a href="{html.escape(link)}" style="background:#dc4a1e;color:#fff;
      padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">Accept invite</a></p>
      <p style="color:#a8a29e;font-size:12px">This link expires in 7 days.</p>
    </div>"""
    return await send_email(to, f"{inviter} invited you to {org_name} on BlackSync", body)
