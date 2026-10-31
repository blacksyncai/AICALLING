"""White-label management is available only inside the unlocked platform admin portal."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.account import Organization
from app.models.white_label import WhiteLabel
from app.services.auth import AdminDep, DbDep
from app.services.white_label import (
    admin_payload,
    brand_for_host,
    clerk_primary_ready,
    encode_logo,
    normalize_domain,
    public_brand,
    reset_domain,
    verify_dns,
)

router = APIRouter(tags=["white-label"])
PREFIX = "/api/admin/orgs/{org_id}/white-label"


class BrandingBody(BaseModel):
    brand_kit: dict | None = None
    inherit_parent: bool = True
    enabled: bool = False
    brand_name: str = Field(default="", max_length=100)
    domain: str = Field(default="", max_length=300)


class LogoBody(BaseModel):
    image_base64: str = Field(max_length=2_800_000)


class ActivateBody(BaseModel):
    hosting_ready: bool = False
    authentication_ready: bool = False


async def config(db, org_id, *, create=False):
    if not await db.get(Organization, org_id):
        raise HTTPException(404, "Account not found")
    row = await db.scalar(
        select(WhiteLabel).where(WhiteLabel.org_id == org_id).with_for_update()
    )
    if row is None and create:
        row = WhiteLabel(
            org_id=org_id, enabled=False, brand_name="", domain_active=False
        )
        db.add(row)
    return row


@router.get(PREFIX)
async def get_settings(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    return await settings_payload(db, await config(db, org_id), org_id)


async def settings_payload(db, row, org_id):
    from app.services.account_tree import effective_brand, parent_info
    parent = await parent_info(db, org_id)
    effective = await effective_brand(db, org_id)
    payload = admin_payload(row)
    payload["domain_active"] = payload["domain_active"] and effective["custom"]
    return {**payload, "parent": parent,
            "inherited_brand": await effective_brand(db, uuid.UUID(parent["id"])) if parent else None,
            "effective_brand": effective}


@router.put(PREFIX)
async def update_settings(
    org_id: uuid.UUID, body: BrandingBody, _: AdminDep, db: DbDep
):
    name = body.brand_name.strip()
    if body.enabled and not name:
        raise HTTPException(422, "Enter a brand name before enabling white label.")
    domain = normalize_domain(body.domain)
    row = await config(db, org_id, create=True)
    if domain != row.domain:
        reset_domain(row, domain)
    row.enabled, row.brand_name = body.enabled, name
    from app.services.brand_kit import validate_kit
    row.inherit_parent = body.inherit_parent
    if body.brand_kit is not None:
        row.brand_kit = validate_kit(body.brand_kit)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            409, "This domain is already reserved by another account."
        ) from None
    from app.services.account_tree import effective_brand
    if not (await effective_brand(db, org_id))["custom"]:
        row.domain_active = False
    return await settings_payload(db, row, org_id)


@router.put(PREFIX + "/logo")
async def upload_logo(org_id: uuid.UUID, body: LogoBody, _: AdminDep, db: DbDep):
    row = await config(db, org_id, create=True)
    row.logo, row.logo_hash = await asyncio.to_thread(encode_logo, body.image_base64)
    await db.flush()
    return await settings_payload(db, row, org_id)


@router.delete(PREFIX + "/logo")
async def remove_logo(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    row = await config(db, org_id)
    if row:
        row.logo, row.logo_hash = None, None
    return await settings_payload(db, row, org_id)


@router.post(PREFIX + "/verify")
async def verify_domain(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    row = await config(db, org_id)
    if row is None:
        raise HTTPException(409, "Save a custom domain first.")
    result = await verify_dns(row)
    return {**await settings_payload(db, row, org_id), "verification": result}


@router.post(PREFIX + "/activate")
async def activate_domain(
    org_id: uuid.UUID, body: ActivateBody, _: AdminDep, db: DbDep
):
    row = await config(db, org_id)
    from app.services.account_tree import effective_brand
    if not row or not (await effective_brand(db, org_id))["custom"]:
        raise HTTPException(409, "Enable this account's branding or inherit an enabled parent kit first.")
    if not body.hosting_ready or not body.authentication_ready:
        raise HTTPException(
            409,
            "Confirm the hostname is attached to hosting with HTTPS and sign-in configured.",
        )
    if settings.clerk_enabled and not clerk_primary_ready():
        raise HTTPException(
            409,
            "Configure WHITE_LABEL_PRIMARY_ORIGIN on the API and web service for Clerk satellite sign-in first.",
        )
    result = await verify_dns(row)
    if not result["verified"]:
        await db.commit()
        raise HTTPException(
            409,
            "Both DNS records must verify before the custom domain can be activated.",
        )
    row.domain_active = True
    return await settings_payload(db, row, org_id)


@router.post(PREFIX + "/deactivate")
async def deactivate_domain(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    row = await config(db, org_id)
    if row:
        row.domain_active = False
    return await settings_payload(db, row, org_id)


@router.get("/api/branding")
async def host_brand(db: DbDep, response: Response, host: str = ""):
    response.headers["Cache-Control"] = "no-store"
    from app.services.account_tree import effective_brand
    row = await brand_for_host(db, host[:253])
    return await effective_brand(db, row.org_id) if row else public_brand(None)


@router.get("/api/branding/logos/{org_id}/{digest}.png")
async def logo(org_id: uuid.UUID, digest: str, db: DbDep):
    data = await db.scalar(
        select(WhiteLabel.logo).where(
            WhiteLabel.org_id == org_id, WhiteLabel.logo_hash == digest
        )
    )
    if not data:
        raise HTTPException(404, "Logo not found")
    return Response(
        data,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
