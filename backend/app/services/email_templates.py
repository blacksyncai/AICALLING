"""
Branded email layout shared by our own emails (Resend) and the sign-in emails
Clerk sends (pushed with scripts/sync_clerk_email_templates.py).

Table-based with inline styles so it renders in Gmail, Outlook and Apple Mail.
Clerk templates keep their {{variables}} — they're filled in by Clerk.
"""

from __future__ import annotations

ORANGE = "#E5531F"
INK = "#1C1917"
MUTED = "#57534E"
FAINT = "#A8A29E"
CANVAS = "#F6F3EF"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def layout(*, title: str, preheader: str, heading: str, body_html: str, footer_note: str = "") -> str:
    """Full HTML document: wordmark, white card, footer."""
    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{CANVAS};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{CANVAS};">{preheader}&#8199;&#65279;&#847;&#8199;&#65279;&#847;&#8199;&#65279;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{CANVAS};">
  <tr><td align="center" style="padding:40px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px;">
      <tr><td style="padding:0 4px 20px 4px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
          <td width="30" height="30" align="center" valign="middle" style="width:30px;height:30px;background:{ORANGE};border-radius:8px;color:#ffffff;font:700 16px/30px {FONT};">B</td>
          <td style="padding-left:10px;font:700 17px/30px {FONT};color:{INK};letter-spacing:-0.2px;">BlackSync</td>
        </tr></table>
      </td></tr>
      <tr><td style="background:#ffffff;border-radius:18px;padding:36px 32px;border:1px solid #ECE7E2;">
        <h1 style="margin:0 0 12px 0;font:700 22px/1.3 {FONT};color:{INK};letter-spacing:-0.3px;">{heading}</h1>
        {body_html}
      </td></tr>
      <tr><td style="padding:20px 8px 0 8px;font:400 12px/1.6 {FONT};color:{FAINT};text-align:center;">
        {footer_note}{"<br>" if footer_note else ""}BlackSync · AI voice agents that call, qualify and book for you
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def p(text: str, *, muted: bool = True, size: int = 15, margin: str = "0 0 16px 0") -> str:
    return f'<p style="margin:{margin};font:400 {size}px/1.6 {FONT};color:{MUTED if muted else INK};">{text}</p>'


def button(href: str, label: str) -> str:
    return f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;"><tr>
  <td align="center" bgcolor="{ORANGE}" style="border-radius:999px;">
    <a href="{href}" target="_blank" style="display:inline-block;padding:13px 28px;font:600 15px/1 {FONT};color:#ffffff;text-decoration:none;border-radius:999px;">{label}</a>
  </td></tr></table>"""


def code_box(code: str) -> str:
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;"><tr>
  <td align="center" style="background:#FDF1EC;border:1px solid #F8D9CC;border-radius:14px;padding:22px 12px;">
    <span style="font:700 34px/1 'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:10px;color:{INK};">{code}</span>
  </td></tr></table>"""


def link_fallback(href: str) -> str:
    return p(f'Button not working? Paste this link into your browser:<br><a href="{href}" style="color:{ORANGE};word-break:break-all;">{href}</a>',
             size=12, margin="0 0 8px 0")


def divider() -> str:
    return '<div style="height:1px;background:#F0ECE8;margin:24px 0;line-height:1px;font-size:1px;">&nbsp;</div>'


def security_note(extra: str = "") -> str:
    return p(f"{extra}If you didn't request this, you can safely ignore this email — nobody can sign in without it.",
             size=12, margin="0")


def requested_line() -> str:
    """Clerk-only: where the request came from."""
    return p("Requested from <strong style=\"color:#57534E;\">{{requested_from}}</strong> on {{requested_at}}.", size=12,
             margin="0 0 8px 0")


# ── Clerk templates (subjects + bodies keep Clerk's {{variables}}) ────────────


def clerk_templates() -> dict[str, dict[str, str]]:
    sign_in_link = layout(
        title="Sign in to BlackSync", preheader="Your secure sign-in link — it expires soon.",
        heading="Sign in to BlackSync",
        body_html=p("Click the button below to sign in. The link works once and expires in {{ttl_minutes}} minutes.")
        + button("{{magic_link}}", "Sign in to BlackSync") + link_fallback("{{magic_link}}") + divider()
        + requested_line() + security_note(),
    )
    sign_up_link = layout(
        title="Finish creating your BlackSync account", preheader="Confirm your email to finish signing up.",
        heading="Confirm your email",
        body_html=p("You're one click away from your BlackSync workspace. Confirm your email to finish creating your account.")
        + button("{{magic_link}}", "Confirm and continue") + link_fallback("{{magic_link}}")
        + p("This link expires in {{ttl_minutes}} minutes.", size=12, margin="0 0 8px 0") + divider()
        + requested_line() + security_note(),
    )
    verify_profile_link = layout(
        title="Verify your email", preheader="Confirm this email address for your BlackSync account.",
        heading="Verify your email",
        body_html=p("Confirm that this address belongs to you to use it with your BlackSync account.")
        + button("{{magic_link}}", "Verify email") + link_fallback("{{magic_link}}") + divider() + security_note(),
    )
    code = layout(
        title="{{otp_code}} is your BlackSync code", preheader="Your BlackSync verification code is {{otp_code}}.",
        heading="Your verification code",
        body_html=p("Enter this code in BlackSync to continue. It expires in 10 minutes.")
        + code_box("{{otp_code}}") + p("For your security, never share this code — BlackSync will never ask you for it.", size=13)
        + divider() + requested_line() + security_note(),
    )
    reset = layout(
        title="Reset your BlackSync password", preheader="Your password reset code is {{otp_code}}.",
        heading="Reset your password",
        body_html=p("Use this code to choose a new password. It expires in 10 minutes.")
        + code_box("{{otp_code}}") + divider() + requested_line()
        + security_note("If you didn't ask to reset your password, your account is still safe. "),
    )
    invitation = layout(
        title="You're invited to BlackSync", preheader="Accept your invitation to BlackSync.",
        heading="You're invited to BlackSync",
        body_html=p("You've been invited to join BlackSync, where AI voice agents call, qualify and book meetings with your leads.")
        + button("{{action_url}}", "Accept invitation") + link_fallback("{{action_url}}") + divider()
        + p("Not expecting this? You can ignore this email.", size=12, margin="0"),
    )
    return {
        "verification_code": {"subject": "{{otp_code}} is your BlackSync code", "body": code},
        "magic_link_sign_in": {"subject": "Your BlackSync sign-in link", "body": sign_in_link},
        "magic_link_sign_up": {"subject": "Confirm your email for BlackSync", "body": sign_up_link},
        "magic_link_user_profile": {"subject": "Verify your email for BlackSync", "body": verify_profile_link},
        "reset_password_code": {"subject": "{{otp_code}} is your BlackSync reset code", "body": reset},
        "invitation": {"subject": "You're invited to BlackSync", "body": invitation},
    }
