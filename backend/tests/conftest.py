import os
import tempfile

# Point the app at a throwaway SQLite DB and a fake OpenAI key before it's imported.
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db.name}"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTH_EMAIL"] = "admin@test.dev"
os.environ["AUTH_PASSWORD"] = "admin-pass-123"
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
