import base64
import hashlib
import hmac
import json
import time

SECRET = "whsec_" + base64.b64encode(b"test-signing-key-1234567890").decode()


def _signed(event: dict, secret: str = SECRET, ts: int | None = None):
    body = json.dumps(event).encode()
    ts = ts or int(time.time())
    key = base64.b64decode(secret.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, f"msg_1.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return body, {"svix-id": "msg_1", "svix-timestamp": str(ts), "svix-signature": f"v1,{sig}",
                  "content-type": "application/json"}


def _event(delivered_by_clerk=False):
    return {"type": "email.created", "data": {
        "to_email_address": "someone@example.com", "subject": "Your verification code",
        "body": "<p>123456</p>", "delivered_by_clerk": delivered_by_clerk, "slug": "verification_code"}}


def test_relays_clerk_emails_from_our_sender(client, monkeypatch):
    from app.config import settings
    from app.services import email

    sent = []

    async def fake_send(to, subject, html, sender=None, kind="other"):
        sent.append((to, subject, html))
        return True

    monkeypatch.setattr(settings, "clerk_webhook_secret", SECRET)
    monkeypatch.setattr(email, "send_email", fake_send)
    body, headers = _signed(_event())
    r = client.post("/api/auth/clerk/email-webhook", content=body, headers=headers)
    assert r.status_code == 200 and r.json() == {"sent": True}
    assert sent == [("someone@example.com", "Your verification code", "<p>123456</p>")]

    # Clerk still delivering it itself → we don't send a second copy.
    body, headers = _signed(_event(delivered_by_clerk=True))
    assert client.post("/api/auth/clerk/email-webhook", content=body, headers=headers).json() == {"sent": False}
    assert len(sent) == 1

    # Forged, tampered or stale requests are refused.
    body, headers = _signed(_event(), secret="whsec_" + base64.b64encode(b"wrong-key").decode())
    assert client.post("/api/auth/clerk/email-webhook", content=body, headers=headers).status_code == 401
    body, headers = _signed(_event())
    assert client.post("/api/auth/clerk/email-webhook", content=body + b" ", headers=headers).status_code == 401
    body, headers = _signed(_event(), ts=int(time.time()) - 3600)
    assert client.post("/api/auth/clerk/email-webhook", content=body, headers=headers).status_code == 401
    assert len(sent) == 1


def test_refused_without_a_secret(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "clerk_webhook_secret", "")
    body, headers = _signed(_event())
    assert client.post("/api/auth/clerk/email-webhook", content=body, headers=headers).status_code == 401
