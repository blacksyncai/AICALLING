def test_public_voice_samples_are_fixed_and_cached(client, monkeypatch):
    from fastapi.responses import Response
    from app.routers import settings as settings_router, voice_samples

    voice_samples._cache.clear()
    calls = []

    async def fake_preview(body):
        calls.append((body.voice_id, body.text))
        return Response(content=b"RIFFfake", media_type="audio/wav")

    monkeypatch.setattr(settings_router, "preview_voice", fake_preview)
    listed = client.get("/api/public/voice-samples").json()["samples"]
    assert [s["name"] for s in listed] == ["Marissa", "Macco", "Lauren", "Kate"]
    for _ in range(2):
        r = client.get("/api/public/voice-samples/marissa.wav", headers={"Authorization": ""})
        assert r.status_code == 200 and r.content == b"RIFFfake" and r.headers["content-type"] == "audio/wav"
    assert calls == [("97f03c16-fab2-4747-b655-9caefbd68fcf",
                      "Hey, this is Marissa. This is a quick preview of how I'll sound on your calls. Does this work for you?")]
    assert client.get("/api/public/voice-samples/anything-else.wav").status_code == 404
