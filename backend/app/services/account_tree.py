from fastapi import HTTPException
from sqlalchemy import select

from app.models.account import Organization
from app.models.account_tree import AccountParent

MAX_DEPTH = 8


async def lineage(db, org_id):
    seen = set()
    while org_id:
        if org_id in seen or len(seen) >= MAX_DEPTH:
            raise HTTPException(
                409, "Account hierarchy is cyclic or exceeds eight levels."
            )
        seen.add(org_id)
        yield org_id
        org_id = await db.scalar(
            select(AccountParent.parent_org_id).where(AccountParent.org_id == org_id)
        )


async def parent_info(db, org_id):
    parent = await db.scalar(
        select(Organization)
        .join(AccountParent, AccountParent.parent_org_id == Organization.id)
        .where(AccountParent.org_id == org_id)
    )
    return {"id": str(parent.id), "name": parent.name} if parent else None


async def check_child_depth(db, parent_id):
    ancestors = [item async for item in lineage(db, parent_id)]
    if len(ancestors) >= MAX_DEPTH:
        raise HTTPException(409, "Accounts support up to eight levels.")


async def effective_brand(db, org_id):
    from app.models.white_label import WhiteLabel
    from app.services.white_label import public_brand

    async for item in lineage(db, org_id):
        row = await db.get(WhiteLabel, item)
        if row and row.enabled:
            return public_brand(row)
        if row and row.inherit_parent is False:
            break
    return public_brand(None)
