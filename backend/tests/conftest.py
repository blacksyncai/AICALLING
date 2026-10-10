import os
import tempfile

# Point the app at a throwaway SQLite DB and a fake OpenAI key before it's imported.
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db.name}"
os.environ["OPENAI_API_KEY"] = "test-key"
for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "DEEPGRAM_API_KEY",
          "CARTESIA_API_KEY", "LIVEKIT_SIP_OUTBOUND_TRUNK_ID", "CALCOM_API_KEY"):
    os.environ[k] = ""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    import main
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def agent_id(client):
    return client.post("/api/agents/", json={"template": "sales_sdr"}).json()["id"]
