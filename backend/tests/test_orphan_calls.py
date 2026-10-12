import asyncio
import uuid
from datetime import datetime, timedelta, timezone


def test_orphaned_call_is_closed(client, monkeypatch):
    from app.config import settings
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.services import outbound_call

    call_id, live_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)

    async def make():
        async with AsyncSessionLocal() as db:
            for cid in (call_id, live_id):
                db.add(CallLog(id=cid, call_type="outbound", to_phone="+14155550123", livekit_room_name=f"call-{cid}",
                               status="connected", started_at=now - timedelta(minutes=6),
                               answered_at=now - timedelta(minutes=5)))
            await db.commit()

    asyncio.run(make())

    class Rooms:
        async def list_rooms(self, _req):
            return type("R", (), {"rooms": [type("Room", (), {"name": f"call-{live_id}"})()]})()

    class FakeLK:
        room = Rooms()

        async def aclose(self):
            pass

    monkeypatch.setattr(type(settings), "livekit_ready", property(lambda self: True))
    monkeypatch.setattr(outbound_call, "_lk", lambda: FakeLK())
    assert asyncio.run(outbound_call.close_orphaned_calls()) == 1

    async def read():
        async with AsyncSessionLocal() as db:
            return await db.get(CallLog, call_id), await db.get(CallLog, live_id)

    gone, live = asyncio.run(read())
    assert gone.status == "completed" and gone.ended_at is not None and gone.duration_seconds == 0
    assert live.status == "connected"  # its room still exists
