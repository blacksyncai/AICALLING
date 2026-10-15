"""
Sign-up emails: a welcome email when a new account is created, then — a day later — an offer of a
free walkthrough call. Sent through Resend (app/services/email.py); nothing is sent without it.

Each email is claimed with an atomic update before sending, so it goes out once even with several
API replicas. Only users who got the welcome email get the follow-up (no emails to older accounts).
"""

from __future__ import annotations

import asyncio
import html
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update

from app.config import settings
from app.models.account import Organization, User
from app.services import email_templates as t
from app.services.email import email_enabled, send_email

log = structlog.get_logger(__name__)

# The walkthrough offer goes out the next day: by then they've either tried it or got stuck.
FOLLOWUP_DELAY = timedelta(hours=24)
# Don't send a stale offer (e.g. after an outage) to someone who signed up long ago.
FOLLOWUP_MAX_AGE = timedelta(days=4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _app_url() -> str:
    return (settings.app_url or "https://blacksync.si").rstrip("/")


def _first(user: User) -> str:
    return html.escape((user.first_name or "").strip())


def _step(n: str, title: str, text: str, pad: str) -> str:
    return f"""<tr>
                  <td style="padding:{pad};vertical-align:top;width:36px;color:#e95420;font-size:19px;font-weight:700;">{n}</td>
                  <td style="padding:{pad.split(' ')[0]} 20px {pad.split(' ')[2]} 0;">
                    <h3 style="margin:0 0 6px;font-size:16px;color:#222;">{title}</h3>
                    <p style="margin:0;font-size:14px;line-height:1.6;color:#666;">{text}</p>
                  </td>
                </tr>"""


_RULE = """<tr><td colspan="2" style="padding:0 20px;"><div style="border-top:1px solid #e9dfd8;"></div></td></tr>"""


def _steps(items: list[tuple[str, str]]) -> str:
    out = []
    for i, (title, text) in enumerate(items):
        pad = "22px 20px 16px" if i == 0 else "18px 20px 22px" if i == len(items) - 1 else "18px 20px 16px"
        out.append(_step(f"{i + 1:02d}", title, text, pad))
    return _RULE.join(out)


def _help_block(booking_url: str | None, heading: str = "Prefer a little help?",
                text: str = "Want a quick walkthrough or prefer to have our team build your agent for you? We're happy to help.",
                label: str = "Book a Free Setup Call") -> str:
    if not booking_url:
        return ""
    book = html.escape(booking_url, quote=True)
    return f"""<tr><td style="padding:0 28px;"><div style="border-top:1px solid #ece8e4;"></div></td></tr>
          <tr>
            <td style="padding:28px;">
              <h2 style="margin:0 0 10px;font-size:19px;color:#222;">{heading}</h2>
              <p style="margin:0 0 20px;font-size:14px;line-height:1.8;color:#666;">{text}</p>
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  <td align="center" style="border:1px solid #e2d6ce;border-radius:10px;">
                    <a href="{book}" target="_blank" style="display:block;padding:15px 20px;color:#bc481d;text-decoration:none;font-size:15px;font-weight:700;">{label} &rarr;</a>
                  </td>
                </tr>
              </table>
              <p style="margin:23px 0 0;text-align:center;font-size:12px;color:#888;">Questions? Use the support chat inside BlackSync.</p>
            </td>
          </tr>"""


def _designed(*, title: str, preheader: str, eyebrow: str, heading: str, intro: str, steps: str,
              cta_label: str, cta_note: str, help_block: str, cta_href: str | None = None) -> str:
    """The BlackSync email layout: dark header, eyebrow + heading, numbered steps, one big button, optional help."""
    href = html.escape(cta_href or f"{_app_url()}/dashboard", quote=True)
    steps_html = (f"""<tr>
            <td style="padding:10px 28px 24px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#faf6f2;border-radius:12px;">
                {steps}
              </table>
            </td>
          </tr>""" if steps else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f1ed;font-family:Arial,Helvetica,sans-serif;color:#242424;">
  <div style="display:none;font-size:1px;color:#f4f1ed;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:#f4f1ed;">
    <tr>
      <td align="center" style="padding:30px 14px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;">
          <tr>
            <td style="background:#171513;padding:22px 28px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background:#f15a24;border-radius:9px;width:38px;height:38px;text-align:center;color:#fff;font-size:25px;font-weight:800;">B</td>
                  <td style="padding-left:12px;color:#fff;font-size:22px;font-weight:700;">BlackSync</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:34px 28px 18px;">
              <p style="margin:0 0 16px;font-size:11px;font-weight:700;letter-spacing:1.5px;color:#e95420;">{eyebrow}</p>
              <h1 style="margin:0 0 16px;font-size:28px;line-height:1.25;letter-spacing:-0.7px;color:#171717;">{heading}</h1>
              <p style="margin:0;font-size:15px;line-height:1.8;color:#555555;">{intro}</p>
            </td>
          </tr>
          {steps_html}
          <tr>
            <td align="center" style="padding:0 28px 30px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  <td align="center" bgcolor="#e95420" style="border-radius:10px;">
                    <a href="{href}" target="_blank" style="display:block;padding:17px 20px;color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;">{cta_label} &rarr;</a>
                  </td>
                </tr>
              </table>
              <p style="margin:14px 0 0;color:#888;font-size:12px;">{cta_note}</p>
            </td>
          </tr>
          {help_block}
        </table>
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;">
          <tr>
            <td align="center" style="padding:22px 16px;">
              <p style="margin:0 0 6px;font-size:12px;color:#888;">BlackSync AI &bull; Your AI calling platform</p>
              <a href="https://blacksync.ai" style="font-size:12px;color:#888;text-decoration:none;">blacksync.ai</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _workspace_line(org_name: str, industry_label: str | None, ready: str = "is ready") -> str:
    company, industry = html.escape(org_name.strip()), html.escape(industry_label or "")
    return (f"Your <strong>{industry}</strong> workspace for {company} {ready}" if industry
            else f"Your workspace for <strong>{company}</strong> {ready}")


def welcome_email(user: User, org_name: str, industry_label: str | None = None,
                  booking_url: str | None = None) -> tuple[str, str]:
    """The sign-up welcome: workspace ready, three steps, open the app — and a setup call for anyone who wants help.

    The call link is the same one as "Have an expert build it" (the expert_booking_url setting)."""
    first = _first(user)
    body = _designed(
        title="Welcome to BlackSync",
        preheader="Your BlackSync workspace is ready. Build and test your first AI agent.",
        eyebrow="YOUR WORKSPACE IS READY",
        heading=f"Welcome to BlackSync{', ' + first if first else ''}.",
        intro=f"{_workspace_line(org_name, industry_label)}, and you've got <strong>complimentary calling credits</strong> "
              "to build, customize, and test your first AI agent. No credit card required.",
        steps=_steps([
            ("Meet Marissa", "Your AI onboarding assistant will learn about your business and help you get started."),
            ("Build your agent", "Choose a voice, describe your business, and let AI help create your first agent."),
            ("Test it live", "Speak to your agent right in your browser and hear how it handles real conversations."),
        ]),
        cta_label="Open My Workspace",
        cta_note="No credit card required &bull; Complimentary calling credits included",
        help_block=_help_block(booking_url),
    )
    return "Welcome to BlackSync — your workspace is ready", body


def catchup_email(user: User, org_name: str, industry_label: str | None = None,
                  booking_url: str | None = None) -> tuple[str, str]:
    """For people who signed up a while ago (before emails went out): pick up where they left off."""
    first = _first(user)
    body = _designed(
        title="Your BlackSync workspace is waiting",
        preheader="Your AI calling workspace is set up — here's the fastest way to see it work.",
        eyebrow="PICK UP WHERE YOU LEFT OFF",
        heading=f"{'Hi ' + first + ', your' if first else 'Your'} workspace is waiting.",
        intro=f"{_workspace_line(org_name, industry_label, 'is set up')}, and your <strong>calling credits</strong> are "
              "still there. Here's the fastest way to hear BlackSync work for your business:",
        steps=_steps([
            ("Talk to Marissa", "Hear an AI agent live in your browser — she'll answer anything about the platform."),
            ("Build your first agent", "Tell BlackSync about your business and it writes the script, voice and call flow."),
            ("Test it, then launch", "Call it from your browser, tweak anything, then point it at your leads or your phone line."),
        ]),
        cta_label="Open My Workspace",
        cta_note="Your calling credits are waiting in your account",
        help_block=_help_block(booking_url, heading="Want us to set it up with you?",
                               text="Book a free 15-minute call — we'll walk you through it or build your first agent "
                                    "with you, live."),
    )
    return "Your BlackSync workspace is waiting", body


def followup_email(user: User, booking_url: str) -> tuple[str, str]:
    """The day-after walkthrough offer."""
    first = _first(user)
    body = _designed(
        title="Want a hand setting up?",
        preheader="Book a free walkthrough and we'll set up your first AI agent with you.",
        eyebrow="FREE WALKTHROUGH",
        heading="Want us to set it up with you?",
        intro=f"Hi{' ' + first if first else ''}, we'd love to help you get your first AI agent calling. Book a free "
              "walkthrough and we'll build it with you live — your script, your voice and your calendar.",
        steps="",
        cta_label="Pick Up Where You Left Off",
        cta_note="Prefer to do it yourself? Everything's in your workspace.",
        help_block=_help_block(booking_url, heading="Book your free walkthrough",
                               text="15 minutes with our team — a quick tour, or we build your first agent with you.",
                               label="Book a Free Walkthrough"),
    )
    return "Want a hand setting up your AI agent?", body


def platform_invite_email(first_name: str, email: str, inviter: str, note: str = "") -> tuple[str, str]:
    """An admin's personal invite for someone without an account: try the platform, sign up with this email."""
    from urllib.parse import quote

    first = html.escape(first_name.strip())
    who = html.escape(inviter.strip() or "The BlackSync team")
    note_html = ""
    if note.strip():
        lines = "<br>".join(html.escape(x) for x in note.strip().splitlines())
        note_html = (f'<br><br><span style="display:block;border-left:3px solid #f15a24;padding:4px 0 4px 14px;'
                     f'color:#444;font-style:italic;">{lines}<br><span style="font-style:normal;color:#888;">'
                     f'&mdash; {who}</span></span>')
    body = _designed(
        title=f"{inviter.strip() or 'BlackSync'} invited you to BlackSync AI",
        preheader=f"{inviter.strip() or 'We'} invited you to test out the new BlackSync AI calling platform.",
        eyebrow="YOU'RE INVITED",
        heading=f"Hey{' ' + first if first else ''}, {who} invited you to test out BlackSync AI.",
        intro="We're opening our new AI calling platform to a few people, and we'd love for you to try it. "
              "BlackSync agents call your leads, answer your phone and book meetings on your calendar &mdash; "
              "and they sound like a real person." + note_html,
        steps=_steps([
            ("Create your account", "Takes under a minute &mdash; no card needed. Use this email so we know it's you."),
            ("Build your first agent", "Tell BlackSync about your business and it writes the script, voice and call flow."),
            ("Hear it call", "Talk to your agent right in your browser, tweak anything, then point it at your leads."),
        ]),
        cta_label="Accept Your Invite",
        cta_note="Free to try &mdash; no card needed",
        help_block="",
        cta_href=f"{_app_url()}/sign-up?email={quote(email.strip())}",
    )
    return f"{inviter.strip() or 'BlackSync'} invited you to try BlackSync AI", body


async def send_welcome(db, user_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    """Send the welcome email once (no-op without Resend)."""
    if not email_enabled():
        return False
    claimed = await db.execute(update(User).where(User.id == user_id, User.welcome_email_at.is_(None))
                               .values(welcome_email_at=_now()))
    await db.commit()
    if claimed.rowcount != 1:
        return False
    user, org = await db.get(User, user_id), await db.get(Organization, org_id)
    if not user or not org:
        return False
    from app.agent import catalog
    from app.services.billing import settings_store

    booking = await settings_store.get(db, "expert_booking_url")
    subject, body = welcome_email(user, org.name, catalog.industry_label(org.industry or "") or None, booking)
    ok = await send_email(user.email, subject, body, kind="welcome")
    log.info("welcome_email", user_id=str(user_id), sent=ok)
    return ok


def send_welcome_soon(user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Fire-and-forget welcome email, so sign-up doesn't wait on the email provider."""
    from app.database import AsyncSessionLocal

    async def go() -> None:
        try:
            async with AsyncSessionLocal() as db:
                await send_welcome(db, user_id, org_id)
        except Exception as exc:
            log.warning("welcome_email_failed", error=str(exc)[:200])

    asyncio.create_task(go())


async def send_due_followups(db, now: datetime | None = None) -> int:
    """Walkthrough offers for users whose welcome email went out at least FOLLOWUP_DELAY ago."""
    if not email_enabled():
        return 0
    from app.services.billing import settings_store

    now = now or _now()
    booking = (await settings_store.get(db, "onboarding_booking_url")) or (await settings_store.get(db, "sales_booking_url"))
    if not booking:
        return 0
    due = (await db.execute(select(User.id).where(
        User.welcome_email_at.is_not(None), User.followup_email_at.is_(None),
        User.welcome_email_at <= now - FOLLOWUP_DELAY, User.welcome_email_at > now - FOLLOWUP_MAX_AGE,
    ).limit(50))).scalars().all()
    sent = 0
    for uid in due:
        claimed = await db.execute(update(User).where(User.id == uid, User.followup_email_at.is_(None))
                                   .values(followup_email_at=now))
        await db.commit()
        if claimed.rowcount != 1:
            continue
        user = await db.get(User, uid)
        if not user:
            continue
        subject, body = followup_email(user, booking)
        if await send_email(user.email, subject, body, kind="walkthrough"):
            sent += 1
        log.info("followup_email", user_id=str(uid))
    return sent


def start_sweeper(interval: float = 600.0):
    """Every 10 minutes, send the walkthrough offers that are due."""
    from app.database import AsyncSessionLocal

    async def _loop() -> None:
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await send_due_followups(db)
            except Exception as exc:  # never let the loop die
                log.warning("followup_sweep_failed", error=str(exc)[:200])
            await asyncio.sleep(interval)

    return asyncio.create_task(_loop())



def alert_new_signup(user, org, industry_label: str, goal_labels: list[str], other_goal: str, team_size: str | None,
                     website: str) -> None:
    """Tell the BlackSync team someone just created an account (fire-and-forget)."""
    import asyncio
    import html

    to = (settings.signup_notify_email or settings.support_notify_email or "").strip()
    if not to or not email_enabled():
        return
    name = " ".join(x for x in (user.first_name, user.last_name) if x) or user.email
    team = {"just_me": "Just them", "2_5": "2–5", "6_20": "6–20", "21_plus": "21+"}.get(team_size or "", "—")
    rows = [("Name", name), ("Email", user.email), ("Phone", user.phone or "—"), ("Company", org.name),
            ("Industry", industry_label), ("Wants", ", ".join(goal_labels) or other_goal or "—"),
            ("Team size", team), ("Website", website or "—")]
    link = f"{(settings.app_url or '').rstrip('/')}/admin/accounts/{org.id}"
    body = ("<p>Someone just created a BlackSync account.</p><table cellpadding='4'>"
            + "".join(f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
            + f"</table><p><a href=\"{html.escape(link)}\">Open the account in the admin portal</a></p>")

    async def go():
        try:
            await send_email(to, f"New signup: {org.name} ({industry_label})", body, kind="signup_alert")
        except Exception as exc:  # an alert must never break signup
            log.warning("signup_alert_failed", error=str(exc)[:200])

    try:
        asyncio.get_running_loop().create_task(go())
    except RuntimeError:
        pass
