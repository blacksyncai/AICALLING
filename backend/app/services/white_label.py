"""Custom domains are verified through DNS, never by fetching a customer-supplied URL."""

import asyncio
import base64
import binascii
import hashlib
import io
import ipaddress
import re
import secrets
import warnings
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.white_label import WhiteLabel


def normalize_domain(raw: str) -> str | None:
    raw = raw.strip().rstrip(".").lower()
    if not raw:
        return None
    try:
        value = raw.encode("idna").decode("ascii")
    except UnicodeError:
        raise HTTPException(
            422, "Enter a valid hostname, such as app.example.com."
        ) from None
    labels = value.split(".")
    if (
        len(value) > 253
        or len(labels) < 2
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        )
        or labels[-1].isdigit()
        or value.endswith((".localhost", ".local", ".internal", ".test"))
    ):
        raise HTTPException(
            422, "Enter a public hostname without a scheme, path, port or wildcard."
        )
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise HTTPException(422, "Use a hostname, not an IP address.")
    if value in {
        urlsplit(settings.app_url).hostname,
        urlsplit(settings.white_label_primary_origin).hostname,
        "blacksync.ai",
        "blacksync.si",
    }:
        raise HTTPException(
            422, "Use a customer hostname rather than the platform's primary domain."
        )
    return value


def cname_target() -> str:
    return settings.white_label_cname_target.strip().lower().rstrip(".")


def clerk_primary_ready() -> bool:
    try:
        parsed = urlsplit(settings.white_label_primary_origin)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def public_brand(row: WhiteLabel | None) -> dict:
    if not row or not row.enabled:
        return {"name": "BlackSync", "logo_url": None, "custom": False}
    return {
        "name": row.brand_name,
        "custom": True,
        "logo_url": f"/api/branding/logos/{row.org_id}/{row.logo_hash}.png"
        if row.logo_hash
        else None,
    }


def admin_payload(row: WhiteLabel | None) -> dict:
    target = cname_target()
    domain = row.domain if row else None
    records = []
    if domain:
        records.append(
            {
                "type": "TXT",
                "name": f"_blacksync.{domain}",
                "value": f"blacksync-verification={row.verification_token}",
            }
        )
        if target:
            records.append({"type": "CNAME", "name": domain, "value": target})
    return {
        "enabled": bool(row and row.enabled),
        "brand_name": row.brand_name if row else "",
        "domain": domain or "",
        "domain_active": bool(
            row
            and row.domain_active
            and row.enabled
            and row.verified_target == target
            and target
        ),
        "dns_verified": bool(
            row and row.dns_verified_at and row.verified_target == target and target
        ),
        "dns_verified_at": row.dns_verified_at.isoformat()
        if row and row.dns_verified_at
        else None,
        "logo_url": f"/api/branding/logos/{row.org_id}/{row.logo_hash}.png"
        if row and row.logo_hash
        else None,
        "dns_records": records,
        "hosting_configured": bool(target),
        "clerk_enabled": settings.clerk_enabled,
    }


async def dns_values(host: str, record_type: str) -> list[str]:
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        response = await client.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": host, "type": record_type},
            headers={"Accept": "application/dns-json"},
        )
        response.raise_for_status()
        result = response.json()
    if result.get("Status") not in (0, 3):
        raise ValueError("DNS resolver could not complete the query")
    code = {"TXT": 16, "CNAME": 5}[record_type]
    return [
        str(a["data"])
        for a in result.get("Answer", [])
        if a.get("type") == code and a.get("name", "").rstrip(".").lower() == host
    ]


async def verify_dns(row: WhiteLabel) -> dict:
    target = cname_target()
    if not row.domain or not target:
        raise HTTPException(
            409,
            "Save a domain and configure WHITE_LABEL_CNAME_TARGET on the server first.",
        )
    try:
        txt, aliases = await asyncio.gather(
            dns_values(f"_blacksync.{row.domain}", "TXT"),
            dns_values(row.domain, "CNAME"),
        )
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(
            502,
            "DNS lookup is temporarily unavailable. Try again; no verification was granted.",
        ) from None
    token = f"blacksync-verification={row.verification_token}"
    ownership = token in [
        "".join(re.findall(r'"([^"]*)"', t)) if '"' in t else t for t in txt
    ]
    routing = target in [alias.lower().rstrip(".") for alias in aliases]
    row.dns_verified_at = datetime.now(UTC) if ownership and routing else None
    row.verified_target = target if ownership and routing else None
    if not (ownership and routing):
        row.domain_active = False
    return {
        "ownership": ownership,
        "routing": routing,
        "verified": ownership and routing,
    }


def encode_logo(encoded: str) -> tuple[bytes, str]:
    if len(encoded) > 2_800_000:
        raise HTTPException(413, "Choose an image smaller than 2 MB.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2_000_000:
            raise HTTPException(413, "Choose an image smaller than 2 MB.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if (
                    image.format not in ("PNG", "JPEG", "WEBP")
                    or image.width * image.height > 16_000_000
                ):
                    raise ValueError("Unsupported image")
                image.load()
                image = image.convert("RGBA")
                image.thumbnail((512, 512))
                image.info.clear()
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                data = output.getvalue()
    except (
        binascii.Error,
        ValueError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        raise HTTPException(
            422, "Upload a valid PNG, JPEG or WebP image (up to 16 megapixels)."
        ) from None
    return data, hashlib.sha256(data).hexdigest()


async def brand_for_host(db: AsyncSession, host: str) -> WhiteLabel | None:
    host = host.lower().strip().rstrip(".")
    return (
        await db.scalar(
            select(WhiteLabel).where(
                WhiteLabel.domain == host,
                WhiteLabel.enabled.is_(True),
                WhiteLabel.domain_active.is_(True),
                WhiteLabel.verified_target == cname_target(),
                WhiteLabel.dns_verified_at.is_not(None),
            )
        )
        if cname_target()
        else None
    )


async def request_brand(db: AsyncSession, request: Request) -> WhiteLabel | None:
    if hasattr(request.state, "white_label"):
        return request.state.white_label
    # The trusted web ingress must replace, rather than append, X-Forwarded-Host.
    host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", "")
    ).lower()
    if "," in host or "/" in host or "@" in host:
        return None
    row = await db.scalar(
        select(WhiteLabel).where(WhiteLabel.domain == host.split(":")[0].rstrip("."))
    )
    if row and not (
        row.enabled
        and row.domain_active
        and row.dns_verified_at
        and row.verified_target == cname_target()
        and cname_target()
    ):
        raise HTTPException(
            403,
            "This custom workspace is not active yet. Use the platform's main sign-in page.",
        )
    request.state.white_label = row
    return request.state.white_label


def reset_domain(row: WhiteLabel, domain: str | None) -> None:
    row.domain = domain
    row.verification_token = secrets.token_urlsafe(32) if domain else None
    row.dns_verified_at = None
    row.verified_target = None
    row.domain_active = False
