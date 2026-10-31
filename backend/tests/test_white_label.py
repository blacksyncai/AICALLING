import asyncio
import base64
import io
import uuid

import httpx
import pytest
from PIL import Image

from app.config import settings
from app.services import white_label
from tests.test_accounts import _login, _new_account


@pytest.fixture
def branding(client, make_client, monkeypatch):
    monkeypatch.setattr(
        settings, "white_label_cname_target", "web-service.up.railway.app"
    )
    org, email = _new_account(client, name="Acme Voice")
    owner = _login(make_client, email)
    url = f"/api/admin/orgs/{org['id']}/white-label"
    yield org, owner, url
    client.post("/api/auth/switch-org", json={"org_id": None})


def save(client, url, **changes):
    body = {
        "enabled": True,
        "brand_name": "Acme Voice",
        "domain": f"app-{uuid.uuid4().hex[:8]}.example.com",
    }
    body.update(changes)
    response = client.put(url, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def dns(monkeypatch, config, *, ownership=True, routing=True):
    records = {r["type"]: r for r in config["dns_records"]}

    async def lookup(host, kind):
        if kind == "TXT":
            return [f'"{records[kind]["value"]}"'] if ownership else ['"wrong-token"']
        return (
            [records[kind]["value"] + "."] if routing else ["wrong-target.example.com."]
        )

    monkeypatch.setattr(white_label, "dns_values", lookup)


def activate(client, url):
    return client.post(
        url + "/activate", json={"hosting_ready": True, "authentication_ready": True}
    )


def test_only_unlocked_platform_admin_can_manage_branding(
    client, make_client, branding
):
    _org, owner, url = branding
    visitor = make_client()
    for method, suffix, body in (
        ("get", "", None),
        ("put", "", {}),
        ("put", "/logo", {"image_base64": ""}),
        ("delete", "/logo", None),
        ("post", "/verify", None),
        ("post", "/activate", {}),
        ("post", "/deactivate", None),
    ):
        kwargs = {"json": body} if body is not None else {}
        assert visitor.request(method, url + suffix, **kwargs).status_code == 401
        assert owner.request(method, url + suffix, **kwargs).status_code == 403
    locked = _login(make_client, "admin@test.dev", "admin-pass-123")
    assert locked.get(url).status_code == 423
    assert (
        locked.put(url, json={"enabled": True, "brand_name": "Nope"}).status_code == 423
    )
    assert client.get(url).json()["enabled"] is False
    assert client.get(f"/api/admin/orgs/{uuid.uuid4()}/white-label").status_code == 404


@pytest.mark.parametrize(
    "domain",
    [
        "https://app.example.com",
        "app.example.com/path",
        "*.example.com",
        "localhost",
        "127.0.0.1",
        "app.localhost",
        "app.local",
        "app.internal",
        "foo.com:443",
        "user@example.com",
        "-bad.example.com",
        "blacksync.ai",
        "blacksync.si",
    ],
)
def test_invalid_domains_rejected(client, branding, domain):
    _, _, url = branding
    assert (
        client.put(
            url, json={"enabled": True, "brand_name": "Acme", "domain": domain}
        ).status_code
        == 422
    )


def test_normalize_names_and_reject_blank_brand(client, branding):
    _, _, url = branding
    assert save(client, url, domain=" APP.Example.COM. ")["domain"] == "app.example.com"
    assert (
        client.put(url, json={"enabled": True, "brand_name": "   "}).status_code == 422
    )
    assert (
        white_label.normalize_domain("app.bücher.example")
        == "app.xn--bcher-kva.example"
    )


def test_domain_cannot_be_claimed_by_another_account(client, branding):
    _, _, url = branding
    data = save(client, url)
    other, _ = _new_account(client)
    other_url = f"/api/admin/orgs/{other['id']}/white-label"
    response = client.put(
        other_url,
        json={"enabled": True, "brand_name": "Other", "domain": data["domain"]},
    )
    assert response.status_code == 409
    assert client.get(url).json()["domain"] == data["domain"]


@pytest.mark.parametrize(
    "ownership,routing", [(False, True), (True, False), (False, False), (True, True)]
)
def test_both_dns_records_and_hosting_confirmation_required(
    client, branding, monkeypatch, ownership, routing
):
    _, _, url = branding
    data = save(client, url)
    dns(monkeypatch, data, ownership=ownership, routing=routing)
    checked = client.post(url + "/verify").json()
    assert checked["dns_verified"] is (ownership and routing)
    assert checked["domain_active"] is False
    assert client.post(url + "/activate", json={}).status_code == 409
    response = activate(client, url)
    assert response.status_code == (200 if ownership and routing else 409)
    assert client.get(url).json()["domain_active"] is (ownership and routing)


def test_missing_hosting_target_and_dns_outage_fail_closed(
    client, branding, monkeypatch
):
    _, _, url = branding
    save(client, url)
    monkeypatch.setattr(settings, "white_label_cname_target", "")
    assert client.post(url + "/verify").status_code == 409
    assert not client.get(url).json()["hosting_configured"]
    monkeypatch.setattr(settings, "white_label_cname_target", "service.example.com")

    async def outage(*args):
        raise httpx.ConnectError("resolver unavailable")

    monkeypatch.setattr(white_label, "dns_values", outage)
    assert client.post(url + "/verify").status_code == 502
    assert not client.get(url).json()["dns_verified"]


def test_domain_change_rotates_proof_and_disabling_revokes_host(
    client, branding, monkeypatch
):
    _, owner, url = branding
    data = save(client, url)
    dns(monkeypatch, data)
    assert activate(client, url).status_code == 200
    host = {"x-forwarded-host": data["domain"]}
    assert owner.get("/api/auth/me", headers=host).status_code == 200
    assert client.get("/api/branding", params={"host": data["domain"]}).json()["custom"]
    changed = save(client, url, domain="new-host.example.com")
    assert not changed["domain_active"] and not changed["dns_verified"]
    assert changed["dns_records"][0]["value"] != data["dns_records"][0]["value"]
    assert not client.get("/api/branding", params={"host": data["domain"]}).json()[
        "custom"
    ]
    dns(monkeypatch, changed)
    assert activate(client, url).status_code == 200
    save(client, url, domain=changed["domain"], enabled=False)
    assert (
        owner.get(
            "/api/auth/me", headers={"x-forwarded-host": changed["domain"]}
        ).status_code
        == 403
    )


def test_changed_dns_disables_active_domain_and_target_change_is_not_trusted(
    client, branding, monkeypatch
):
    _, _, url = branding
    data = save(client, url)
    dns(monkeypatch, data)
    assert activate(client, url).status_code == 200
    monkeypatch.setattr(settings, "white_label_cname_target", "new-ingress.example.com")
    assert not client.get("/api/branding", params={"host": data["domain"]}).json()[
        "custom"
    ]
    assert not client.get(url).json()["domain_active"]
    monkeypatch.setattr(
        settings, "white_label_cname_target", data["dns_records"][1]["value"]
    )
    dns(monkeypatch, data, routing=False)
    assert not client.post(url + "/verify").json()["domain_active"]


def test_custom_domain_selects_only_its_account_without_granting_membership(
    client, make_client, branding, monkeypatch
):
    org, owner, url = branding
    data = save(client, url)
    dns(monkeypatch, data)
    assert activate(client, url).status_code == 200
    other, email = _new_account(client)
    stranger = _login(make_client, email)
    headers = {"x-forwarded-host": data["domain"]}
    assert stranger.get("/api/auth/me", headers=headers).status_code == 403
    assert stranger.get("/api/agents/", headers=headers).status_code == 403
    # Even an admin's different active account is overridden by this hostname.
    client.post("/api/auth/switch-org", json={"org_id": other["id"]})
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["org"]["id"] == org["id"] and me["branding"]["name"] == "Acme Voice"
    assert all(m["org_id"] == org["id"] for m in me["memberships"])
    assert (
        client.post(
            "/api/auth/switch-org", headers=headers, json={"org_id": other["id"]}
        ).status_code
        == 403
    )
    assert client.get("/api/auth/me").json()["org"]["id"] == other["id"]
    assert owner.get("/api/auth/me").json()["branding"]["name"] == "Acme Voice"
    assert not client.get(
        "/api/branding", params={"host": "unknown.example.com"}
    ).json()["custom"]


def test_pending_custom_host_cannot_show_another_accounts_data(client, branding):
    _, owner, url = branding
    data = save(client, url)
    assert (
        owner.get(
            "/api/agents/", headers={"x-forwarded-host": data["domain"]}
        ).status_code
        == 403
    )


def test_logo_is_validated_sanitized_and_can_be_removed(client, branding):
    _, owner, url = branding
    save(client, url, domain="")
    image = io.BytesIO()
    Image.new("RGBA", (900, 200), (30, 40, 50, 200)).save(image, format="PNG")
    response = client.put(
        url + "/logo",
        json={"image_base64": base64.b64encode(image.getvalue()).decode()},
    )
    assert response.status_code == 200, response.text
    logo_url = response.json()["logo_url"]
    asset = owner.get(logo_url)
    assert asset.status_code == 200 and asset.headers["content-type"] == "image/png"
    assert asset.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(asset.content)) as decoded:
        assert decoded.width == 512 and decoded.mode == "RGBA"
    assert owner.get("/api/auth/me").json()["branding"]["logo_url"] == logo_url
    assert (
        client.put(url + "/logo", json={"image_base64": "not base64"}).status_code
        == 422
    )
    svg = base64.b64encode(b'<svg onload="alert(1)"></svg>').decode()
    assert client.put(url + "/logo", json={"image_base64": svg}).status_code == 422
    assert (
        client.put(url + "/logo", json={"image_base64": "A" * 2_800_001}).status_code
        == 422
    )
    assert client.delete(url + "/logo").json()["logo_url"] is None
    assert client.get(logo_url).status_code == 404


def test_dns_transport_uses_only_fixed_resolver_and_exact_owner(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "Status": 0,
                "Answer": [
                    {
                        "name": "app.example.com.",
                        "type": 5,
                        "data": "service.example.com.",
                    },
                    {
                        "name": "other.example.com.",
                        "type": 5,
                        "data": "wrong.example.com.",
                    },
                ],
            },
        )

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        white_label.httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(handle)),
    )
    assert asyncio.run(white_label.dns_values("app.example.com", "CNAME")) == [
        "service.example.com."
    ]
    assert requests[0].url.host == "cloudflare-dns.com"


def test_clerk_activation_requires_satellite_origin(client, branding, monkeypatch):
    from app.models.account import User
    from app.services import auth

    _, _, url = branding
    admin_id = uuid.UUID(client.get("/api/auth/me").json()["user"]["id"])
    data = save(client, url)
    dns(monkeypatch, data)

    async def fake_clerk_user(request, db):
        return await db.get(User, admin_id)

    monkeypatch.setattr(auth, "_clerk_user", fake_clerk_user)
    monkeypatch.setattr(settings, "clerk_secret_key", "local-test-key")
    monkeypatch.setattr(settings, "white_label_primary_origin", "")
    assert activate(client, url).status_code == 409
    monkeypatch.setattr(
        settings, "white_label_primary_origin", "https://blacksync.example"
    )
    assert activate(client, url).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "http://app.example.com",
        "https://",
        "https://user:pass@app.example.com",
        "https://app.example.com/path",
        "https://app.example.com?redirect=evil",
    ],
)
def test_invalid_clerk_origins_are_not_ready(monkeypatch, origin):
    monkeypatch.setattr(settings, "white_label_primary_origin", origin)
    assert not white_label.clerk_primary_ready()
