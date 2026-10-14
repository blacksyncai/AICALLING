import pytest

from app.config import settings
from app.services import clerk

PROFILES = {
    "user_admin": {"id": "user_admin", "first_name": "Hamza", "last_name": "B",
                   "primary_email_address_id": "e1", "email_addresses": [{"id": "e1", "email_address": "Admin@Test.dev", "verification": {"status": "verified"}}]},
    "user_rep": {"id": "user_rep", "first_name": "Rep", "last_name": "Two",
                 "primary_email_address_id": "e2", "email_addresses": [{"id": "e2", "email_address": "rep2@clerk.dev", "verification": {"status": "verified"}}]},
    "user_stranger": {"id": "user_stranger", "first_name": "Sam", "primary_email_address_id": "e3",
                      "email_addresses": [{"id": "e3", "email_address": "sam@nowhere.dev", "verification": {"status": "verified"}}]},
}


@pytest.fixture
def clerk_mode(monkeypatch):
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_fake")

    async def verify(token):
        return token if token in PROFILES else None

    async def get_user(cid):
        return PROFILES[cid]

    monkeypatch.setattr(clerk, "verify_session_token", verify)
    monkeypatch.setattr(clerk, "get_user", get_user)


def bearer(cid):
    return {"Authorization": f"Bearer {cid}"}


def test_clerk_sign_in_links_users_and_invites(client, make_client, clerk_mode):
    c = make_client()
    assert c.get("/api/auth/me").status_code == 401
    assert c.get("/api/auth/me", headers=bearer("forged")).status_code == 401
    assert c.post("/api/auth/login", json={"email": "admin@test.dev", "password": "admin-pass-123"}).status_code == 400

    # The bootstrap super-admin is matched by email on first Clerk sign-in.
    me = c.get("/api/auth/me", headers=bearer("user_admin")).json()
    assert me["user"]["email"] == "admin@test.dev" and me["user"]["is_superadmin"]
    assert me["auth_provider"] == "clerk" and me["org"]["name"] == "BlackSync"

    # An invite is accepted automatically when the invitee signs up with that email.
    inv = c.post("/api/account/org/invites", headers=bearer("user_admin"),
                 json={"email": "rep2@clerk.dev", "role": "admin"}).json()
    rep = c.get("/api/auth/me", headers=bearer("user_rep")).json()
    assert rep["org"]["name"] == "BlackSync" and rep["role"] == "admin" and not rep["user"]["is_superadmin"]
    assert c.get(f"/api/auth/invites/{inv['invite_url'].rsplit('/', 1)[1]}").status_code == 404

    # Someone who signs up uninvited has a login but no account until they're invited.
    stranger = c.get("/api/auth/me", headers=bearer("user_stranger")).json()
    assert stranger["org"] is None and stranger["memberships"] == []
    assert c.get("/api/agents/", headers=bearer("user_stranger")).status_code == 403
    inv2 = c.post("/api/account/org/invites", headers=bearer("user_admin"),
                  json={"email": "someone-else@x.dev"}).json()
    token = inv2["invite_url"].rsplit("/", 1)[1]
    joined = c.post(f"/api/auth/invites/{token}/join", headers=bearer("user_stranger")).json()
    assert joined["org"]["name"] == "BlackSync" and joined["role"] == "member"

    # Passwords and sign-in emails are Clerk's job now.
    assert c.post("/api/account/password", headers=bearer("user_rep"),
                  json={"current_password": "x", "new_password": "y" * 10}).status_code == 400
    assert c.patch("/api/account/profile", headers=bearer("user_rep"), json={"email": "new@x.dev"}).status_code == 400
    assert c.patch("/api/account/profile", headers=bearer("user_rep"), json={"phone": "+1555"}).status_code == 200


def test_admin_creates_clerk_logins(client, clerk_mode, monkeypatch):
    created = {}

    async def find(email):
        return None

    async def create(email, password, first="", last=""):
        created[email] = password
        return {"id": "user_new_owner"}

    monkeypatch.setattr(clerk, "find_user_by_email", find)
    monkeypatch.setattr(clerk, "create_user", create)
    r = client.post("/api/admin/orgs", headers=bearer("user_admin"),
                    json={"name": "Clerk Co", "owner_email": "owner@clerkco.dev"}).json()
    assert r["owner_status"] == "created" and created["owner@clerkco.dev"] == r["temporary_password"]


def test_unverified_email_never_matches_an_account():
    from app.services.clerk import primary_email

    assert primary_email({"primary_email_address_id": "e1", "email_addresses": [
        {"id": "e1", "email_address": "hamza@blacksync.ai", "verification": {"status": "unverified"}}]}) == ""
    assert primary_email({"primary_email_address_id": "e1", "email_addresses": [
        {"id": "e1", "email_address": "Ops@Acme.dev", "verification": {"status": "verified"}}]}) == "ops@acme.dev"
