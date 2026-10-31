import uuid

import pytest

from app.services.brand_kit import DEFAULT_KIT
from tests.test_accounts import _login, _new_account


def kit(client, org, **changes):
    response = client.put(
        f"/api/admin/orgs/{org['id']}/white-label",
        json={
            "enabled": True,
            "brand_name": "Northstar Voice",
            "brand_kit": {**DEFAULT_KIT, "primary": "#2458a6", "sidebar": "#10283e"},
            **changes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def child(client, parent, email=None, name="Branch office"):
    response = client.post(
        f"/api/admin/orgs/{parent['id']}/children",
        json={
            "name": name,
            "owner_email": email or f"owner-{uuid.uuid4().hex[:8]}@brand.example",
            "password": "branch-password-123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_child_and_grandchild_inherit_and_can_override_brand_kit(client, make_client):
    root, email = _new_account(client)
    kit(client, root)
    branch = child(client, root, email)
    leaf = child(client, branch, email, "Local office")
    owner = _login(make_client, email)
    assert (
        owner.post("/api/auth/switch-org", json={"org_id": leaf["id"]}).status_code
        == 200
    )
    assert owner.get("/api/auth/me").json()["branding"]["kit"]["primary"] == "#2458a6"
    settings = client.get(f"/api/admin/orgs/{leaf['id']}/white-label").json()
    assert settings["parent"]["id"] == branch["id"]
    assert settings["effective_brand"]["name"] == "Northstar Voice"
    kit(
        client,
        branch,
        brand_name="Branch Voice",
        brand_kit={**DEFAULT_KIT, "primary": "#176b4b"},
    )
    assert owner.get("/api/auth/me").json()["branding"]["name"] == "Branch Voice"
    kit(client, leaf, enabled=False, inherit_parent=False)
    assert not owner.get("/api/auth/me").json()["branding"]["custom"]
    kit(client, leaf, enabled=False, inherit_parent=True)
    assert owner.get("/api/auth/me").json()["branding"]["name"] == "Branch Voice"


def test_parent_membership_does_not_grant_child_data_or_management_access(
    client, make_client
):
    parent, email = _new_account(client)
    branch = child(client, parent)
    owner = _login(make_client, email)
    assert owner.get(f"/api/admin/orgs/{parent['id']}/children").status_code == 403
    assert (
        owner.post(
            f"/api/admin/orgs/{parent['id']}/children",
            json={"name": "No", "owner_email": email},
        ).status_code
        == 403
    )
    assert owner.get(f"/api/admin/orgs/{branch['id']}/white-label").status_code == 403
    assert (
        owner.post("/api/auth/switch-org", json={"org_id": branch["id"]}).status_code
        == 403
    )
    assert branch["credits_balance"] == 0 and not branch["unlimited_credits"]
    assert (
        client.get(f"/api/admin/orgs/{parent['id']}/children").json()["children"][0][
            "id"
        ]
        == branch["id"]
    )


def test_parent_cannot_be_deleted_with_descendants(client):
    parent, _ = _new_account(client)
    branch = child(client, parent)
    result = client.request(
        "DELETE",
        f"/api/admin/orgs/{parent['id']}",
        json={"confirm_name": parent["name"]},
    )
    assert result.status_code == 409
    assert client.get(f"/api/admin/orgs/{branch['id']}").status_code == 200


def test_depth_is_bounded_and_missing_parents_do_not_create_orphans(client):
    parent, email = _new_account(client)
    for depth in range(7):
        parent = child(client, parent, email, f"Level {depth + 2}")
    assert (
        client.post(
            f"/api/admin/orgs/{parent['id']}/children",
            json={"name": "Too deep", "owner_email": email},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/admin/orgs/{uuid.uuid4()}/children",
            json={"name": "Missing parent", "owner_email": email},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"primary": "red; background:url(https://evil.example)"},
        {"primary": "#abc"},
        {"font": "https://evil.example/font.css"},
        {"button_shape": "expression(alert(1))"},
        {"text": "#ffffff", "surface": "#ffffff"},
        {"sidebar": "#ffffff"},
        {"surface": "#000000", "text": "#ffffff"},
        {"arbitrary_css": "body{display:none}"},
    ],
)
def test_safe_tokens_and_contrast_are_enforced(client, bad):
    org, _ = _new_account(client)
    response = client.put(
        f"/api/admin/orgs/{org['id']}/white-label",
        json={
            "enabled": True,
            "brand_name": "Northstar",
            "brand_kit": {**DEFAULT_KIT, **bad},
        },
    )
    assert response.status_code == 422
    assert not client.get(f"/api/admin/orgs/{org['id']}/white-label").json()["enabled"]


def test_inherited_brand_does_not_inherit_parent_domain(client, monkeypatch):
    from app.config import settings
    from app.services import white_label

    monkeypatch.setattr(settings, "white_label_cname_target", "ingress.example.com")
    parent, _ = _new_account(client)
    kit(client, parent, domain="parent.example.com")
    branch = child(client, parent)
    child_url = f"/api/admin/orgs/{branch['id']}/white-label"
    settings = client.get(child_url).json()
    assert settings["domain"] == "" and settings["dns_records"] == []
    config = kit(
        client, branch, enabled=False, inherit_parent=True, domain="child.example.com"
    )

    async def dns(host, record):
        record_data = next(r for r in config["dns_records"] if r["type"] == record)
        return [record_data["value"]]

    monkeypatch.setattr(white_label, "dns_values", dns)
    assert (
        client.post(
            child_url + "/activate",
            json={"hosting_ready": True, "authentication_ready": True},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/branding", params={"host": "child.example.com"}).json()["name"]
        == "Northstar Voice"
    )
