"""Resolve FUB identity before routing; journal contact creation before external writes."""
from sqlalchemy import select
from app.models.lead import Lead
from app.models.radar_automation import now
from app.services.contacts import normalize_phone
from app.services.crm import sync
from app.services.crm.http import CrmError
from app.services.crm.providers import _DNC_TAGS, split_name

LEGACY_UNLINKED = "This contact isn't linked to the selected CRM. Import/link it before routing."


class ContactReviewRequired(CrmError):
    """A user setting or ambiguous result requires intervention, not an automatic retry."""


def identity(lead):
    phone = normalize_phone(lead.phone)
    email = (lead.email or "").strip().casefold()
    return phone, email if "@" in email else ""


def same_person(person, phone, email):
    phones = {normalize_phone(p.get('value', '')) for p in (person.get('phones') or []) if isinstance(p, dict)}
    emails = {str(e.get('value', '')).strip().casefold() for e in (person.get('emails') or []) if isinstance(e, dict)}
    return bool((phone and phone in phones) or (email and email in emails))


def check_person(person):
    if not isinstance(person, dict):
        raise ContactReviewRequired("Follow Up Boss returned an invalid person record. Review the connection.")
    if not str(person.get('id', '')).isascii() or not str(person.get('id', '')).isdigit() or int(person['id']) < 1:
        raise ContactReviewRequired("Follow Up Boss did not confirm a valid contact ID. Link the contact manually.")
    tags = {str(t).casefold() for t in (person.get('tags') or [])}
    if (person.get('stage') or '').casefold() in {'trash', 'closed', 'past client', 'sphere'} or tags & _DNC_TAGS or person.get('doNotCall') is True:
        raise ContactReviewRequired("The Follow Up Boss contact is closed or suppressed; routing was not applied.")
    return str(person['id'])


async def find_exact(http, phone, email):
    found = {}
    for field, value in [('phone', phone), ('email', email)]:
        if not value:
            continue
        page = await http.request('GET', '/v1/people', params={field: value, 'limit': 2,
            'fields': 'id,name,phones,emails,stage,tags'})
        rows = page.get('people', [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ContactReviewRequired('Follow Up Boss returned an invalid contact lookup response. Review the connection before retrying.')
        if (page.get('_metadata') or {}).get('nextLink') or len(rows) > 1:
            raise ContactReviewRequired('Multiple Follow Up Boss contacts may match. Link the intended person before retrying.')
        for row in rows:
            if not same_person(row, phone if field == 'phone' else '', email if field == 'email' else ''):
                raise ContactReviewRequired('Follow Up Boss returned a contact without an exact identity match. Link the intended person manually.')
            found[check_person(row)] = row
    if len(found) > 1:
        raise ContactReviewRequired('Phone and email match different Follow Up Boss people. Resolve the conflicting contact links before retrying.')
    return next(iter(found.values()), None)


async def resolve(db, job, conn, lead):
    """Return a durable linked ID. Never create before rule conditions have matched."""
    if lead.org_id != conn.org_id or job.org_id != conn.org_id:
        raise ContactReviewRequired('Contact and CRM connection must belong to this workspace.')
    if conn.provider != 'followupboss':
        if not (lead.crm_refs or {}).get(conn.provider):
            raise ContactReviewRequired(LEGACY_UNLINKED)
        return
    _, http = sync.http_for(conn)
    # Refresh under a row lock: other Radar jobs may have linked the same contact.
    lead = await db.scalar(select(Lead).where(Lead.id == lead.id, Lead.org_id == conn.org_id)
                           .with_for_update().execution_options(populate_existing=True))
    if lead is None or lead.do_not_call:
        raise ContactReviewRequired('This contact is unavailable or marked do not call.')
    phone, email = identity(lead)
    linked = str((lead.crm_refs or {}).get(conn.provider) or '')
    pending = (job.result or {}).get('pending_contact')
    if pending:
        from app.services.crm.assistant import fingerprint
        if pending.get('connection') != fingerprint(conn) or (pending.get('phone'), pending.get('email')) != (phone, email):
            raise ContactReviewRequired('The CRM account or contact identity changed after a pending creation. Review the previous request before routing.')
    if linked:
        if not linked.isascii() or not linked.isdigit() or int(linked) < 1:
            raise ContactReviewRequired('The saved Follow Up Boss contact link is invalid. Relink it before routing.')
        person = await http.request('GET', f'/v1/people/{int(linked)}')
        check_person(person)
        if (person.get('phones') or person.get('emails')) and not same_person(person, phone, email):
            raise ContactReviewRequired('The saved Follow Up Boss person no longer matches this contact. Relink it before routing.')
        status = 'already_linked'
    else:
        if not phone and not email:
            raise ContactReviewRequired('A phone number or email is required to find or create the Follow Up Boss contact.')
        person = await find_exact(http, phone, email)
        status = 'linked_existing'
        if person is None:
            if pending:
                raise ContactReviewRequired('A previous contact creation may have reached Follow Up Boss. No exact match is visible yet. Review the CRM before retrying; Radar will not create a second contact automatically.')
            if not sync.conn_settings(conn)['create_contacts']:
                raise ContactReviewRequired('No matching Follow Up Boss contact was found. Enable “Create people who aren’t in Follow Up Boss” in Integrations → Follow Up Boss, or link an existing person, then retry. No contact was created.')
            # Commit an intent before POST so a timeout/crash can only trigger a read-only reconciliation.
            from app.services.crm.assistant import fingerprint
            job.result = {**(job.result or {}), 'pending_contact': {
                'phone': phone, 'email': email, 'connection': fingerprint(conn)}}
            await db.commit()
            lead = await db.scalar(select(Lead).where(Lead.id == lead.id, Lead.org_id == conn.org_id)
                                   .with_for_update().execution_options(populate_existing=True))
            if lead is None or lead.do_not_call:
                raise ContactReviewRequired('This contact is unavailable or marked do not call.')
            if identity(lead) != (phone, email):
                raise ContactReviewRequired('The contact identity changed before creation. Review it before retrying.')
            # Reconcile again after reacquiring the lock; a parallel job or normal call sync may have linked it.
            linked = str((lead.crm_refs or {}).get(conn.provider) or '')
            if linked:
                person = await http.request('GET', f'/v1/people/{int(linked)}')
                check_person(person)
                if not same_person(person, phone, email):
                    raise ContactReviewRequired('The newly linked person does not match this contact. Review the CRM link.')
            else:
                person = await find_exact(http, phone, email)
            if person is None:
                # Re-read the setting immediately before creation; never overwrite global settings.
                await db.refresh(conn)
                if fingerprint(conn) != job.result['pending_contact']['connection']:
                    raise ContactReviewRequired('The connected CRM account changed before creation. Review the previous request.')
                if not sync.conn_settings(conn)['create_contacts']:
                    raise ContactReviewRequired('Contact creation was disabled before the request. No new contact was requested.')
                first, last = split_name(lead.name)
                payload = {'firstName': first or phone, 'lastName': last, 'source': 'BlackSync AI'}
                if phone: payload['phones'] = [{'value': phone}]
                if email: payload['emails'] = [{'value': email}]
                response = await http.request('POST', '/v1/people', params={'deduplicate': 'true'}, json=payload)
                created = response.get('person', response)
                key = check_person(created)
                person = await http.request('GET', f'/v1/people/{int(key)}')
                if not same_person(person, phone, email):
                    raise ContactReviewRequired('Follow Up Boss did not confirm the created contact identity. Review it before retrying.')
                status = 'created_or_deduplicated'
    key = check_person(person)
    lead.crm_refs = {**(lead.crm_refs or {}), conn.provider: key}
    receipt = {'provider': conn.provider, 'id': key, 'status': status,
               'name': person.get('name') or lead.name, 'confirmed_at': now().isoformat()}
    job.result = {k: v for k, v in {**(job.result or {}), 'contact': receipt}.items() if k != 'pending_contact'}
    await db.commit()
