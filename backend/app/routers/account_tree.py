"""Nested tenant management stays behind the platform admin lock."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.models.account import Organization
from app.models.account_tree import AccountParent
from app.routers.admin import OrgCreate, create_org
from app.services.account_tree import effective_brand, parent_info
from app.services.auth import AdminDep, DbDep

router = APIRouter(prefix="/api/admin/orgs", tags=["account hierarchy"])


@router.get("/{org_id}/children")
async def children(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    if not await db.get(Organization, org_id):
        raise HTTPException(404, "Account not found")
    rows = (
        await db.scalars(
            select(Organization)
            .join(AccountParent, AccountParent.org_id == Organization.id)
            .where(AccountParent.parent_org_id == org_id)
            .order_by(Organization.name)
        )
    ).all()
    return {
        "parent": await parent_info(db, org_id),
        "children": [
            {
                "id": str(row.id),
                "name": row.name,
                "status": row.status,
                "branding": await effective_brand(db, row.id),
            }
            for row in rows
        ],
    }


@router.post("/{org_id}/children", status_code=201)
async def create_child(
    org_id: uuid.UUID, body: OrgCreate, request: Request, admin: AdminDep, db: DbDep
):
    return {
        **await create_org(body, request, admin, db, parent_org_id=org_id),
        "parent_org_id": str(org_id),
    }
