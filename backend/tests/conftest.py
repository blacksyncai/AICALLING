import os
import tempfile

# Point the app at a throwaway SQLite DB and a fake OpenAI key before it's imported.
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
# TEST_DATABASE_URL runs the suite against a real database instead (e.g. Postgres, to check row locking).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{_db.name}"
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DB_NULL_POOL"] = "1"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["RUN_STARTUP_JOBS"] = "0"
os.environ["AUTH_EMAIL"] = "admin@test.dev"
os.environ["AUTH_PASSWORD"] = "admin-pass-123"
os.environ["ADMIN_PASSWORD"] = "portal-pass-456"
for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "DEEPGRAM_API_KEY",
          "CARTESIA_API_KEY", "LIVEKIT_SIP_OUTBOUND_TRUNK_ID", "CALCOM_API_KEY", "RESEND_API_KEY"):
    os.environ[k] = ""

import pytest
from fastapi.testclient import TestClient

ADMIN = {"email": "admin@test.dev", "password": "admin-pass-123"}


@pytest.fixture(scope="session")
def app():
    import main
    return main.app


@pytest.fixture(scope="session")
def client(app):
    """Signed in as the platform super-admin, working in the house account."""
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json=ADMIN).status_code == 200
        assert c.post("/api/admin/unlock", json={"password": "portal-pass-456"}).status_code == 200
        yield c


@pytest.fixture
def make_client(app, client):
    """Fresh, signed-out clients (e.g. for a sub-account's own login)."""
    clients = []

    def _make():
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def agent_id(client):
    return client.post("/api/agents/", json={"template": "sales_sdr"}).json()["id"]


@pytest.fixture(autouse=True)
def _any_local_time_ok(monkeypatch):
    """Dialing tests run at any hour; the contact-local-time check has its own tests (test_quiet_hours.py)."""
    from app.services import quiet_hours

    monkeypatch.setattr(quiet_hours, "ok_to_call", lambda phone, now: True)
