"""Bandwidth's callbacks for calls we place through it (answer → hand the call to LiveKit; disconnect)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.services import bandwidth

router = APIRouter(prefix="/api/telephony/bandwidth", tags=["telephony"])


def _check(c: str, s: str) -> None:
    if not bandwidth.valid_signature(c, s):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/answer")
async def answer(c: str = "", s: str = ""):
    _check(c, s)
    return Response(content=bandwidth.answer_bxml(c), media_type="application/xml")


@router.post("/disconnect")
async def disconnect(request: Request, c: str = "", s: str = ""):
    _check(c, s)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    await bandwidth.on_disconnect(c, payload if isinstance(payload, dict) else {})
    return {"ok": True}
