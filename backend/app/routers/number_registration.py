"""One-time business authorization, not a customer-side per-number registration workflow."""
import uuid
from typing import Literal
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from app.services.auth import CtxDep, ManagerDep, DbDep
from app.models.builder import BusinessProfile
from app.models.number_registration import RegistrationAuthorization as Authorization, NumberRegistration
from app.services.number_registration import latest_authorization, wake_org, normalize_name

router = APIRouter(prefix='/api/phone-numbers/registration', tags=['caller identity'])
Provider = Literal['signalwire_cnam','hiya','first_orion']


class BusinessAuthorization(BaseModel):
    legal_name: str = Field(min_length=1,max_length=255)
    caller_name: str
    business_details: dict = Field(default_factory=dict)
    providers: list[Provider] = Field(min_length=1,max_length=3)
    fees_authorized: list[Provider] = Field(default_factory=list,max_length=3)
    registration_authorized: Literal[True] = Field(description="Authorize these providers to register current and future phone numbers assigned to this business using the approved caller name and business details. Revocable.")
    # Customer-approved evidence reference (e.g. signed terms/consent record); actor and time captured server-side.
    evidence: str = Field(min_length=3,max_length=2000)

    @field_validator('legal_name', 'evidence')
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value: raise ValueError('This field must not be blank.')
        return value

    @field_validator('caller_name')
    @classmethod
    def validate_name(cls, value): return normalize_name(value)


def public_authorization(a):
    return {'id':str(a.id), 'legal_name':a.legal_name, 'caller_name':a.caller_name,
            'providers':a.providers, 'fees_authorized':a.fees_authorized,
            'authorized_at':a.created_at.isoformat(), 'revoked':bool(a.revoked_at)} if a else None


@router.get('/business')
async def business(ctx: CtxDep, db: DbDep):
    a = await latest_authorization(db, ctx.org.id)
    profile = (await db.execute(select(BusinessProfile).where(BusinessProfile.org_id==ctx.org.id))).scalar_one_or_none()
    return {'authorization': public_authorization(a),
            'suggested_business_name': profile.name if profile and profile.name else ctx.org.name,
            'suggested_website': profile.website if profile else '',
            'note':'Business name suggestions are not registration authorization.'}


@router.post('/authorization')
async def authorize(body: BusinessAuthorization, ctx: ManagerDep, db: DbDep):
    if len(str(body.business_details)) > 16000: raise HTTPException(422,'Business details are too large.')
    providers = sorted(set(body.providers))
    fees = sorted(set(body.fees_authorized))
    if not set(fees).issubset(providers): raise HTTPException(422,'Fee authorization must match selected providers.')
    from app.models.account import Organization
    await db.execute(select(Organization.id).where(Organization.id==ctx.org.id).with_for_update())
    previous = await latest_authorization(db, ctx.org.id)
    # Repeated requests with the same consent do not replace pending provider requests.
    if previous and not previous.revoked_at and (previous.legal_name, previous.caller_name,
            previous.details, sorted(previous.providers), sorted(previous.fees_authorized)) == (
            body.legal_name.strip(), body.caller_name, body.business_details, providers, fees):
        return public_authorization(previous)
    if previous and not previous.revoked_at: previous.revoked_at = datetime.now(timezone.utc)
    a = Authorization(org_id=ctx.org.id, legal_name=body.legal_name.strip(), caller_name=body.caller_name,
        details=body.business_details, providers=providers, fees_authorized=fees,
        authorized_by=ctx.user.id, evidence=body.evidence)
    db.add(a)
    await db.flush()
    await wake_org(db, ctx.org.id)
    await db.commit()
    return public_authorization(a)


@router.delete('/authorization')
async def revoke(ctx: ManagerDep, db: DbDep):
    a = await latest_authorization(db, ctx.org.id)
    if a and not a.revoked_at: a.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    # Wake all outstanding providers so revocation causes cleanup, not merely a stopped queue.
    from sqlalchemy import update
    from app.services.number_registration import now
    await db.execute(update(NumberRegistration).where(NumberRegistration.org_id==ctx.org.id,
        NumberRegistration.status!='removed').values(next_at=now(), status='queued'))
    await db.commit()
    return {'revoked':True}


from app.services.auth import AdminDep
from app.models.number_registration import ProviderBusiness


class CarrierOrder(BaseModel):
    order_reference: str = Field(min_length=1,max_length=255)
    evidence: str = Field(min_length=3,max_length=2000)


@router.get('/admin/carrier-actions')
async def carrier_actions(admin: AdminDep, db: DbDep):
    actions = (await db.execute(select(NumberRegistration).where(
        NumberRegistration.provider=='signalwire_attestation', NumberRegistration.phase=='register',
        NumberRegistration.status!='removed').order_by(NumberRegistration.created_at).limit(100))).scalars().all()
    return [{'action_id':str(j.id),'org_id':str(j.org_id),'number':j.number,
             'action':'signalwire_business_verification_order','status':j.status,
             'attestation_level':'unknown','required_action':j.prerequisite} for j in actions]


@router.put('/admin/carrier-orders/{org_id}')
async def record_carrier_order(org_id: uuid.UUID, body: CarrierOrder, admin: AdminDep, db: DbDep):
    from app.models.account import Organization
    org = (await db.execute(select(Organization).where(Organization.id==org_id).with_for_update())).scalar_one_or_none()
    if not org:raise HTTPException(404,'Account not found.')
    record = (await db.execute(select(ProviderBusiness).where(ProviderBusiness.org_id==org_id,
        ProviderBusiness.provider=='signalwire_attestation'))).scalar_one_or_none()
    if not record:
        record=ProviderBusiness(org_id=org_id,provider='signalwire_attestation');db.add(record)
    record.external_id=body.order_reference.strip()
    if not record.external_id:raise HTTPException(422,'A real carrier order reference is required.')
    record.status='submitted'
    record.response={'order_reference':record.external_id,'evidence':body.evidence,'recorded_by':str(admin.id),
                     'note':'Manually submitted carrier business verification order; per-call attestation remains unknown.'}
    record.updated_at=datetime.now(timezone.utc)
    await wake_org(db,org_id);await db.commit()
    return {'order_reference':record.external_id,'business_verification_status':'submitted','attestation_level':'unknown'}
