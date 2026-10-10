import base64

from app.routers import speech


def test_transcribe(client, make_client, monkeypatch):
    seen = {}

    async def fake(audio, mime, language):
        seen.update(size=len(audio), mime=mime, language=language)
        return "Call homeowners who asked for a quote."

    monkeypatch.setattr(speech, "transcribe_audio", fake)
    audio = base64.b64encode(b"\x1aE\xdf\xa3" + b"0" * 4000).decode()
    r = client.post("/api/speech/transcribe", json={"audio_base64": audio, "mime_type": "audio/webm;codecs=opus", "language": "en"})
    assert r.status_code == 200 and r.json() == {"text": "Call homeowners who asked for a quote."}
    assert seen == {"size": 4004, "mime": "audio/webm;codecs=opus", "language": "en"}

    assert client.post("/api/speech/transcribe", json={"audio_base64": base64.b64encode(b"x").decode()}).status_code == 400
    assert client.post("/api/speech/transcribe", json={"audio_base64": "%%%"}).status_code == 400
    assert make_client().post("/api/speech/transcribe", json={"audio_base64": audio}).status_code == 401

    async def boom(*a):
        raise RuntimeError("down")

    monkeypatch.setattr(speech, "transcribe_audio", boom)
    r = client.post("/api/speech/transcribe", json={"audio_base64": audio})
    assert r.status_code == 502 and "understand" in r.json()["detail"]
