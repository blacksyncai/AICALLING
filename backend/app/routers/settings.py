"""
Settings router — which integrations are configured, and the voice catalog.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict

import httpx
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.agent.models import LANGUAGES, RUNTIME_DEFAULT_MODEL, model_catalog, model_groups
from app.agent import inference_tts
from app.agent.mistral_tts import MISTRAL_TTS_MODEL, is_mistral_voice, synthesize_wav
from app.agent import elevenlabs_tts
from app.agent.voices import FEATURED_VOICES, HIDDEN_VOICE_IDS, VOICE_MODELS
from app.config import settings
from app.services.auth import CtxDep, DbDep, ManagerDep, get_current_user

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(get_current_user)])

# Shown when no Cartesia key is set (or the API is unreachable). Any Cartesia
# voice ID can also be pasted into the agent editor.
_FALLBACK_VOICES = [
    {"id": "a167e0f3-df7e-4d52-a9c3-f949145efdab", "name": "Blake – Helpful Agent", "gender": "male", "language": "en"},
    {"id": "79a125e8-cd45-4c13-8a67-188112f4dd22", "name": "British Lady", "gender": "female", "language": "en"},
    {"id": "a0e99841-438c-4a64-b679-ae501e7d6091", "name": "Barbershop Man", "gender": "male", "language": "en"},
]

_CARTESIA_URL = "https://api.cartesia.ai"
_CARTESIA_VERSION = "2025-04-16"
_CACHE_TTL = 3600

# Raw Cartesia items, cached for an hour: {"at", "public", "owned"}.
_voice_cache: dict = {"at": 0.0, "public": None, "owned": None}

# Accent words looked for in a voice's own name/description (longest first so
# "Latin American" wins over "American"). No match → accent is null.
_ACCENTS = [
    "Latin American", "New Zealand", "South African", "New York", "European Portuguese",
    "American", "British", "Australian", "Canadian", "Irish", "Scottish", "Welsh", "Indian",
    "Southern", "Nigerian", "Kenyan", "Jamaican", "Texan", "Midwestern", "Californian",
    "Cockney", "Mexican", "Castilian", "Argentinian", "Argentine", "Colombian", "Brazilian",
    "Parisian", "Quebecois", "Québécois", "Swiss", "Austrian", "Filipino", "Singaporean",
]
_ACCENT_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in _ACCENTS) + r")\b", re.IGNORECASE)
_GENDERS = {"feminine": "female", "female": "female", "masculine": "male", "male": "male",
            "gender_neutral": "neutral", "neutral": "neutral"}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.cartesia_api_key}",
        "X-API-Key": settings.cartesia_api_key,
        "Cartesia-Version": _CARTESIA_VERSION,
    }


async def _fetch_cartesia_voices() -> tuple[list[dict], list[dict]]:
    """(listed voices, account-owned voices) straight from Cartesia.

    Only the voices the picker shows are fetched — the house voices and the configured
    premium/standard ids — one request each, rather than the whole public library."""
    import asyncio

    wanted = list(dict.fromkeys([v["id"] for v in FEATURED_VOICES if not v.get("provider")] + _ids(settings.premium_voice_ids)
                                + _ids(settings.standard_voice_ids)))[:50]
    async with httpx.AsyncClient(timeout=10.0) as client:
        async def one(vid: str) -> dict | None:
            try:
                resp = await client.get(f"{_CARTESIA_URL}/voices/{vid}", headers=_headers())
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                body = resp.json()
                return body if isinstance(body, dict) and body.get("id") else None
            except httpx.HTTPError as exc:
                log.debug("cartesia_voice_failed", voice_id=vid, error=str(exc))
                return None

        public = [v for v in await asyncio.gather(*(one(vid) for vid in wanted)) if v]
    if not public:
        raise RuntimeError("no voices could be loaded from Cartesia")
    owned: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_CARTESIA_URL}/voices", headers=_headers(),
                                    params={"limit": 100, "is_owner": "true"})
            resp.raise_for_status()
            body = resp.json()
            owned = body.get("data", []) if isinstance(body, dict) else body
    except Exception as exc:
        log.debug("cartesia_owned_voices_failed", error=str(exc))
    return public, owned


def _ids(raw: str) -> list[str]:
    return [i.strip() for i in (raw or "").split(",") if i.strip()]


def _premium_ids(owned_ids: set[str]) -> list[str]:
    """House premium selections, account-owned voices, and PREMIUM_VOICE_IDS."""
    clones = [v["id"] for v in FEATURED_VOICES if v.get("clone") or v.get("category") == "premium"]
    return list(dict.fromkeys(clones + sorted(owned_ids) + _ids(settings.premium_voice_ids)))


def _standard_ids(premium: set[str]) -> list[str]:
    """The curated stock voices: house voices that aren't clones, plus STANDARD_VOICE_IDS."""
    house = [v["id"] for v in FEATURED_VOICES if not v.get("clone")]
    return [i for i in dict.fromkeys(house + _ids(settings.standard_voice_ids)) if i not in premium]


def _accent(raw: dict) -> str | None:
    if "accent" in raw:  # explicit metadata (or already resolved) — use as-is
        return raw["accent"].strip() or None if isinstance(raw["accent"], str) else None
    m = _ACCENT_RE.search(f"{raw.get('name') or ''} {raw.get('description') or ''}")
    if not m:
        return None
    hit = m.group(1).lower()
    return next(a for a in _ACCENTS if a.lower() == hit)


def _normalize(raw: dict, *, owned: bool, premium: bool, can_preview: bool) -> dict:
    gender = _GENDERS.get(str(raw.get("gender") or "").strip().lower())
    out = {
        "id": raw.get("id"),
        "name": raw.get("name") or raw.get("id"),
        "provider": raw.get("provider") or "cartesia",
        "category": "premium" if premium else "standard",
        "language": (raw.get("language") or None),
        "accent": _accent(raw),
        "gender": gender,
        "description": (raw.get("description") or "")[:200],
        "is_clone": owned,
        "preview": bool(settings.elevenlabs_api_key) if raw.get("provider") == "elevenlabs" else
                   settings.livekit_ready if inference_tts.is_inference_voice(raw.get("id")) else can_preview,
        "models": [elevenlabs_tts.MODEL] if raw.get("provider") == "elevenlabs" else
                  [inference_tts.model_of(raw["id"])] if inference_tts.is_inference_voice(raw.get("id")) else
                  [MISTRAL_TTS_MODEL] if raw.get("provider") == "mistral" else list(VOICE_MODELS),
        "status": "available",
    }
    if raw.get("family"):  # one speaker offered in several tones (picker groups these into one row)
        out["family"], out["tone"] = raw["family"], raw.get("tone")
    if owned:
        out["mine"] = True  # kept for older clients
    return out


def build_catalog(public: list[dict], owned: list[dict], *, can_preview: bool) -> list[dict]:
    """Premium (cloned voices) + Standard (curated house voices) as one de-duplicated list.

    Only listed voices are included — not Cartesia's whole public library. Catalog metadata
    wins over the featured list's; featured descriptions fill gaps.
    """
    owned = [v for v in owned if v.get("id") not in HIDDEN_VOICE_IDS]
    public = [v for v in public if v.get("id") not in HIDDEN_VOICE_IDS]
    owned_ids = {v.get("id") for v in owned if v.get("id")}
    premium = _premium_ids(owned_ids)
    premium_set = set(premium)
    standard = _standard_ids(premium_set)
    listed = premium_set | set(standard)
    by_id: dict[str, dict] = {}
    for raw in [*owned, *public]:
        if raw.get("id") and raw["id"] not in by_id:
            by_id[raw["id"]] = raw
    for f in FEATURED_VOICES:
        # Catalog metadata (language, gender…) + the house name/description.
        cat = {k: v for k, v in (by_id.get(f["id"]) or {}).items() if v not in (None, "")}
        merged = {**f, **cat, "name": f["name"], "description": f.get("description") or cat.get("description", "")}
        merged["accent"] = _accent(cat) if cat else f.get("accent")  # Cartesia's metadata, else the entry's own
        by_id[f["id"]] = merged
    voices = [
        _normalize(raw, owned=vid in owned_ids, premium=vid in premium_set, can_preview=can_preview)
        for vid, raw in by_id.items() if vid in listed
    ]
    house_clones = {f["id"] for f in FEATURED_VOICES if f.get("clone")}
    for v in voices:
        if v["id"] in house_clones:
            v["is_clone"] = True
    rank = {vid: i for i, vid in enumerate(premium + standard)}
    voices.sort(key=lambda v: (v["category"] != "premium", rank.get(v["id"], len(rank))))
    return voices


def _categories(voices: list[dict]) -> list[dict]:
    return [
        {"key": "premium", "label": settings.voice_premium_label,
         "count": sum(v["category"] == "premium" for v in voices)},
        {"key": "standard", "label": settings.voice_standard_label,
         "count": sum(v["category"] == "standard" for v in voices)},
    ]


def _voices_response(source: str, voices: list[dict], message: str | None = None) -> dict:
    by_id = {v["id"]: v for v in voices}
    return {
        "source": source,
        "voices": voices,
        "featured": [by_id[f["id"]] for f in FEATURED_VOICES if f["id"] in by_id],
        "categories": _categories(voices),
        "preview_available": bool(settings.cartesia_api_key or settings.elevenlabs_api_key),
        "message": message,
    }


def _fallback_response(message: str) -> dict:
    voices = build_catalog(_FALLBACK_VOICES, [], can_preview=bool(settings.cartesia_api_key))
    return _voices_response("fallback", voices, message)


@router.get("/status")
async def integration_status(user=Depends(get_current_user)):
    caps = {
        "chat_test": bool(settings.openai_api_key),
        "web_call": settings.voice_ready,
        "phone_call": settings.phone_ready,
        "post_call_analysis": bool(settings.openai_api_key),
    }
    if not getattr(user, "is_superadmin", False):
        return {"capabilities": caps}  # customers only need to know what works, not what it runs on
    return {
        "database": "sqlite" if settings.is_sqlite else "postgres",
        "integrations": {
            "openai": bool(settings.openai_api_key),
            "livekit": settings.livekit_ready,
            "deepgram": bool(settings.deepgram_api_key),
            "cartesia": bool(settings.cartesia_api_key),
            "sip_trunk": bool(settings.livekit_sip_outbound_trunk_id),
            "calcom": bool(settings.calcom_api_key and settings.calcom_event_type_id),
        },
        "capabilities": {
            "chat_test": bool(settings.openai_api_key),
            "web_call": settings.voice_ready,
            "phone_call": settings.phone_ready,
            "post_call_analysis": bool(settings.openai_api_key),
        },
        "livekit_url": settings.livekit_url,
        "agent_name": settings.livekit_agent_name,
    }


async def _account_clone_ids(db) -> set[str]:
    from sqlalchemy import select

    from app.models.account_voice import AccountVoice

    return set((await db.execute(select(AccountVoice.voice_id))).scalars().all())


@router.get("/voices")
async def list_voices(db: DbDep):
    """The Cartesia voice catalog, split into premium / standard categories. Customers' own clones are left out
    (each account sees its own through /voices/mine)."""
    if not settings.cartesia_api_key:
        return _fallback_response("The full voice library isn't available right now — showing a short list.")
    fresh = _voice_cache["public"] is not None and time.time() - _voice_cache["at"] < _CACHE_TTL
    if not fresh:
        try:
            public, owned = await _fetch_cartesia_voices()
        except Exception as exc:
            log.warning("cartesia_voices_failed", error=str(exc))
            return _fallback_response("Couldn't load the full voice library — showing a short list.")
        if not public and not owned:
            return _fallback_response("No voices came back from the voice library — showing a short list.")
        _voice_cache.update(at=time.time(), public=public, owned=owned)
    private = await _account_clone_ids(db)
    owned = [v for v in _voice_cache["owned"] if v.get("id") not in private]
    voices = build_catalog(_voice_cache["public"], owned, can_preview=True)
    return _voices_response("cartesia", voices)


@router.get("/models")
async def list_models():
    """LLM models the voice runtime can run, grouped, plus language support."""
    models = model_catalog()
    return {
        "models": models,
        "groups": model_groups(models),
        "default": RUNTIME_DEFAULT_MODEL,
        "languages": LANGUAGES,
    }


class VoicePreview(BaseModel):
    voice_id: str
    text: str = Field(default="Hi, this is your AI agent. How does this voice sound?", max_length=300)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = "en"
    tone: str = ""  # warm | upbeat | calm | friendly | empathetic (see voice_tuning.TONES)


# Small LRU of generated preview WAVs keyed by (voice_id, speed, language, text).
_PREVIEW_CACHE_MAX = 50
_preview_cache: OrderedDict[tuple, bytes] = OrderedDict()


async def _synthesize(payload: dict) -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_CARTESIA_URL}/tts/bytes",
            headers={"Authorization": f"Bearer {settings.cartesia_api_key}", "Cartesia-Version": _CARTESIA_VERSION},
            json=payload,
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Couldn't generate a voice preview — try again.")
    return resp.content


async def _preview_mistral(voice_id: str, text: str) -> Response:
    if not settings.mistral_api_key:
        raise HTTPException(status_code=400, detail="Voice previews aren't available yet.")
    key = (voice_id, text)
    if key not in _preview_cache:
        try:
            _preview_cache[key] = await synthesize_wav(voice_id, text)
        except httpx.HTTPError as exc:
            log.warning("mistral_preview_failed", error=str(exc))
            raise HTTPException(status_code=502, detail="Couldn't generate a voice preview — try again.")
        while len(_preview_cache) > _PREVIEW_CACHE_MAX:
            _preview_cache.popitem(last=False)
    _preview_cache.move_to_end(key)
    return Response(content=_preview_cache[key], media_type="audio/wav")


@router.post("/voices/preview")
async def preview_voice(body: VoicePreview):
    """Speak a short line in the chosen voice (WAV) so it can be auditioned in the editor."""
    voice_id = body.voice_id.strip()
    if elevenlabs_tts.is_elevenlabs_voice(voice_id):
        if not settings.elevenlabs_api_key:
            raise HTTPException(status_code=400, detail="Voice previews aren't available yet.")
        key = (voice_id, round(body.speed, 2), body.language, body.text)
        if key not in _preview_cache:
            try:
                _preview_cache[key] = await elevenlabs_tts.synthesize_wav(
                    voice_id, body.text, speed=body.speed, language=body.language)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            except httpx.HTTPError:
                raise HTTPException(status_code=502, detail="Couldn't generate this voice preview. Please try again.")
            while len(_preview_cache) > _PREVIEW_CACHE_MAX:
                _preview_cache.popitem(last=False)
        _preview_cache.move_to_end(key)
        return Response(content=_preview_cache[key], media_type="audio/wav")
    if inference_tts.is_inference_voice(voice_id):
        if not settings.livekit_ready:
            raise HTTPException(status_code=400, detail="Voice previews aren't available yet.")
        key = (voice_id, round(body.speed, 2), body.language, body.text)
        if key not in _preview_cache:
            try:
                _preview_cache[key] = await inference_tts.synthesize_wav(
                    voice_id, body.text, speed=body.speed, language=body.language)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            except Exception as exc:
                log.warning("inference_preview_failed", error=str(exc)[:200])
                raise HTTPException(status_code=502, detail="Couldn't generate this voice preview. Please try again.")
            while len(_preview_cache) > _PREVIEW_CACHE_MAX:
                _preview_cache.popitem(last=False)
        _preview_cache.move_to_end(key)
        return Response(content=_preview_cache[key], media_type="audio/wav")
    if is_mistral_voice(voice_id):
        return await _preview_mistral(voice_id, body.text)
    if not settings.cartesia_api_key:
        raise HTTPException(status_code=400, detail="Voice previews aren't available yet.")
    lang = body.language if body.language not in ("multi", "") else "en"
    from app.agent.voice_tuning import TONES

    emotion = TONES.get(body.tone.lower()) if body.tone else None
    key = (voice_id, round(body.speed, 2), lang, body.text, emotion)
    if key in _preview_cache:
        _preview_cache.move_to_end(key)
        return Response(content=_preview_cache[key], media_type="audio/wav")
    payload = {
        "model_id": VOICE_MODELS[0],
        "transcript": body.text,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000},
        "language": lang,
        "generation_config": {"speed": body.speed, **({"emotion": emotion} if emotion else {})},
    }
    audio = await _synthesize(payload)
    _preview_cache[key] = audio
    while len(_preview_cache) > _PREVIEW_CACHE_MAX:
        _preview_cache.popitem(last=False)
    return Response(content=audio, media_type="audio/wav")


# ── Account-wide pronunciations ───────────────────────────────────────────────


class PronunciationsIn(BaseModel):
    pronunciations: list[dict] = Field(default_factory=list, max_length=200)


def _clean_pronunciations(raw: list[dict]) -> list[dict]:
    out, seen = [], set()
    for p in raw:
        word, say = str(p.get("word") or "").strip()[:60], str(p.get("say") or "").strip()[:120]
        if word and say and word.lower() not in seen:
            seen.add(word.lower())
            out.append({"word": word, "say": say})
    return out


@router.get("/pronunciations")
async def get_pronunciations(ctx: CtxDep):
    """How every agent in this account says certain words (on top of each agent's own list)."""
    return {"pronunciations": ctx.org.pronunciations or []}


@router.put("/pronunciations")
async def save_pronunciations(body: PronunciationsIn, ctx: ManagerDep, db: DbDep):
    ctx.org.pronunciations = _clean_pronunciations(body.pronunciations) or None
    await db.commit()
    return {"pronunciations": ctx.org.pronunciations or []}


# ── Your own voice (instant clone) ────────────────────────────────────────────

MAX_ACCOUNT_VOICES = 5
_CLONE_MAX_BYTES = 10 * 1024 * 1024


def _account_voice_dict(v) -> dict:
    return {"id": v.voice_id, "name": v.name, "provider": "cartesia", "category": "premium", "language": v.language,
            "accent": None, "gender": None, "description": "Your cloned voice", "is_clone": True, "mine": True,
            "preview": bool(settings.cartesia_api_key), "models": list(VOICE_MODELS), "status": "available",
            "created_at": v.created_at.isoformat() if v.created_at else None}


@router.get("/voices/mine")
async def my_voices(ctx: CtxDep, db: DbDep):
    """This account's own cloned voices (no other account sees them)."""
    from sqlalchemy import select

    from app.models.account_voice import AccountVoice

    rows = (await db.execute(select(AccountVoice).where(AccountVoice.org_id == ctx.org.id)
                             .order_by(AccountVoice.created_at))).scalars().all()
    return {"voices": [_account_voice_dict(v) for v in rows], "limit": MAX_ACCOUNT_VOICES}


@router.post("/voices/clone", status_code=201)
async def clone_voice(ctx: ManagerDep, db: DbDep, file: UploadFile = File(...), name: str = Form(...),
                      language: str = Form("en")):
    """Clone a voice from a short recording (10 seconds to a few minutes of clear speech)."""
    from sqlalchemy import func, select

    from app.models.account_voice import AccountVoice

    if not settings.cartesia_api_key:
        raise HTTPException(status_code=503, detail="Voice cloning isn't available right now.")
    name = name.strip()[:100]
    if not name:
        raise HTTPException(status_code=400, detail="Give the voice a name.")
    count = await db.scalar(select(func.count()).select_from(AccountVoice).where(AccountVoice.org_id == ctx.org.id))
    if (count or 0) >= MAX_ACCOUNT_VOICES:
        raise HTTPException(status_code=400, detail=f"You can have up to {MAX_ACCOUNT_VOICES} cloned voices. Delete one first.")
    audio = await file.read(_CLONE_MAX_BYTES + 1)
    if len(audio) > _CLONE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="That recording is too big (10 MB max). A minute or two is plenty.")
    if len(audio) < 20_000:
        raise HTTPException(status_code=400, detail="That recording is too short. Record at least 10 seconds of speech.")
    lang = (language or "en").strip().lower()[:8] or "en"
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{_CARTESIA_URL}/voices/clone",
                headers={"Authorization": f"Bearer {settings.cartesia_api_key}", "Cartesia-Version": _CARTESIA_VERSION},
                files={"clip": (file.filename or "voice.wav", audio, file.content_type or "audio/wav")},
                data={"name": f"{name} ({ctx.org.name})"[:100], "language": lang, "mode": "similarity", "enhance": "true"})
    except httpx.HTTPError as exc:
        log.warning("voice_clone_failed", org_id=str(ctx.org.id), error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="Couldn't clone the voice right now. Try again.")
    if resp.status_code >= 400:
        log.warning("voice_clone_rejected", org_id=str(ctx.org.id), status=resp.status_code, body=resp.text[:300])
        raise HTTPException(status_code=400, detail="Couldn't clone that recording. Use a clear recording of one "
                                                    "person talking, with no music or background noise.")
    voice_id = (resp.json() or {}).get("id")
    if not voice_id:
        raise HTTPException(status_code=502, detail="Couldn't clone the voice right now. Try again.")
    row = AccountVoice(org_id=ctx.org.id, voice_id=voice_id, name=name, language=lang, created_by=ctx.user.id)
    db.add(row)
    await db.commit()
    log.info("voice_cloned", org_id=str(ctx.org.id), voice_id=voice_id)
    return _account_voice_dict(row)


@router.delete("/voices/mine/{voice_id}", status_code=204)
async def delete_my_voice(voice_id: str, ctx: ManagerDep, db: DbDep):
    from sqlalchemy import select

    from app.models.account_voice import AccountVoice

    row = (await db.execute(select(AccountVoice).where(AccountVoice.org_id == ctx.org.id,
                                                       AccountVoice.voice_id == voice_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice not found")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.delete(f"{_CARTESIA_URL}/voices/{voice_id}", headers={
                "Authorization": f"Bearer {settings.cartesia_api_key}", "Cartesia-Version": _CARTESIA_VERSION})
    except httpx.HTTPError as exc:
        log.warning("voice_delete_failed", voice_id=voice_id, error=str(exc)[:200])
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
