"""CSV → FUB. Reuse the integration catalog and variable choices; preserve source values."""
import hashlib
import json
import re
from datetime import date, timedelta
from app.models.radar_automation import now
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from app.models.crm import CrmConnection
from app.models.lead import Lead
from app.services.crm import sync, variables
from app.services.contacts import normalize_phone
from app.services.crm.assistant import fingerprint
from app.services.crm.radar_contacts import ContactReviewRequired, check_person, same_person, identity, find_exact

# Only these native fields are writable through the automatic CSV path.
ADDRESS = {'address':'street','street':'street','street_address':'street','mailing_address':'street',
           'mailing_street':'street','mailing_city':'city','mailing_state':'state','mailing_zip':'code','city':'city','town':'city','state':'state','zip':'code','zip_code':'code','zipcode':'code','postal_code':'code'}
RESERVED = {'source','lead_source','stage','status','agent','assigned_agent','owner','lender','background','notes','created','last_activity'}
INTERNAL = {'bs_deal','bs_install','bs_tries','crm_trigger','crm_contacted','crm_stage','crm_tags'}


def values_for(lead):
    values = {k: v for k, v in variables.visible_fields(lead.custom_fields).items() if k not in INTERNAL and not k.startswith('_')}
    for key in ('name','phone','email','company','role'):
        value = getattr(lead,key,None)
        if value not in (None,''):
            values[key] = value
    return values


def convert(value, field):
    text = str(value)
    kind = field.get('type','text')
    if kind == 'text':
        if len(text)>255: raise ValueError('Value retained in CSV snapshot: too long for automatic text-field mapping')
        return text
    if kind == 'number':
        try: number = Decimal(text.replace(',','').removeprefix('$').strip())
        except InvalidOperation: raise ValueError('Not a numeric value')
        if not number.is_finite() or abs(number)>Decimal('1e15'): raise ValueError('Number is outside the automatic mapping range')
        if number == number.to_integral(): return int(number)
        converted=float(number)
        if Decimal(str(converted))!=number: raise ValueError('Number would lose precision')
        return converted
    if kind == 'date':
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',text): raise ValueError('Date must be YYYY-MM-DD')
        return date.fromisoformat(text).isoformat()
    if kind == 'dropdown':
        matches=[x for x in field.get('choices',[]) if str(x).casefold()==text.casefold()]
        if len(matches)!=1: raise ValueError('Value does not match a dropdown option')
        return matches[0]
    raise ValueError('Unsupported custom-field type')


def confirmed(actual, expected, field=None):
    if isinstance(expected,list):
        if not isinstance(actual,list): return False
        def same(row,want):
            for key,value in want.items():
                got=row.get(key)
                if key=='value' and field=='phones':
                    if normalize_phone(got)!=normalize_phone(value): return False
                elif key=='value' and field=='emails':
                    if str(got).casefold()!=str(value).casefold(): return False
                elif got!=value: return False
            return True
        return all(any(same(row,want) for row in actual if isinstance(row,dict)) for want in expected if isinstance(want,dict))
    if isinstance(expected,(int,float)):
        try: return Decimal(str(actual))==Decimal(str(expected))
        except InvalidOperation: return False
    return actual==expected


async def checkpoint(db, job):
    if job.status == 'running':
        job.lease_until = now() + timedelta(minutes=5)
    await db.commit()


async def export(db, job, conn, call, lead):
    if conn.provider!='followupboss': return
    if lead.org_id!=conn.org_id or job.org_id!=conn.org_id or lead.do_not_call:
        raise ContactReviewRequired('CSV data is not available for this workspace/contact.')
    values=values_for(lead)
    # No extra data: keep the already-supported identity/contact path unchanged.
    extra={k:v for k,v in values.items() if k not in {'name','phone','email'}}
    if not extra and lead.intent_source != 'csv': return
    raw=json.dumps(values,ensure_ascii=False,sort_keys=True,indent=2,default=str)
    if len(raw)>250000:
        raise ContactReviewRequired('CSV data is too large to sync safely in one contact snapshot. Review the CSV columns; no source values were discarded.')
    digest=hashlib.sha256(raw.encode()).hexdigest()
    marker=f'[BlackSync CSV {digest}]'
    block=marker+'\nImported CSV data (original values):\n'+raw
    p,http=sync.http_for(conn)
    account_fingerprint=fingerprint(conn)
    fields=await p._custom_fields(http,fresh=True,strict=True) if extra or (job.result or {}).get('pending_csv_field') else []
    pending=(job.result or {}).get('pending_csv_field')
    if pending:
        matched=[f for f in fields if p._slug(f['label'])==p._slug(pending['label'])]
        if pending.get('connection')!=fingerprint(conn) or len(matched)!=1:
            raise ContactReviewRequired('A custom-field creation may have reached FUB but is not confirmed. Review it before retrying; no second create request was sent.')
        job.result={k:v for k,v in job.result.items() if k!='pending_csv_field'}
        await checkpoint(db,job)
    # Existing per-agent integration choices are hints from a CSV/script variable to its CRM field.
    # Their inbound "-" setting is not treated as permission to discard outbound CSV data.
    mapping=((conn.settings or {}).get('var_maps') or {}).get(str(call.agent_id)) or {}
    settings=sync.conn_settings(conn)
    create_allowed=bool(settings.get('csv_create_fields'))
    report={'synced':[], 'unchanged':[], 'conflicts':[], 'unmapped':[], 'warnings':[], 'created_fields':[], 'snapshot':False}
    plans={}; address={}; address_sources={}; collisions=set()

    def choose(key):
        chosen=mapping.get(key)
        slug=p._slug(chosen if chosen not in (None,'','-') else key)
        matches=[f for f in fields if p._slug(f['label']) in {slug,p._slug('CSV '+key) if key in RESERVED else slug} or f['name']==chosen or f['name']==key]
        return matches,slug

    for key,value in extra.items():
        matches,target=choose(key)
        # Property-address columns stay custom; a property's address is not a person's mailing address.
        native_key=(mapping.get(key) if mapping.get(key) not in (None,'','-') else key)
        if not matches and native_key==key and not key.startswith('property_'):
            native_key=variables.auto_field(key,{'address','city','state','zip','price'}) or native_key
        if native_key in ADDRESS and not str(mapping.get(key,'')).startswith('custom'):
            part=ADDRESS[native_key]
            if part in address and str(address[part])!=str(value):
                collisions.add('addresses'); report['conflicts'].append(key)
            address[part]=str(value);address_sources[part]=key
            continue
        if native_key == 'price' and not str(mapping.get(key,'')).startswith('custom'):
            try:
                number=convert(value,{'type':'number'})
                if number!=int(number) or not -2147483648<=int(number)<=2147483647: raise ValueError('Price must fit FUB integer field')
                if 'price' in plans and plans['price'][1]!=int(number):
                    collisions.add('price');report['conflicts'].extend([plans['price'][0],key])
                plans['price']=(key,int(number))
            except (ValueError,OverflowError): report['unmapped'].append(key)
            continue
        if len(matches)>1:
            report['conflicts'].append(key);continue
        field=matches[0] if matches else None
        if field is None and len(str(value))>255:
            report['unmapped'].append(key);continue
        if field is None and create_allowed and len(report['created_fields'])<50:
            label=('CSV '+key if key in RESERVED else key).replace('_',' ').strip().title()[:120]
            pending=(job.result or {}).get('pending_csv_field')
            if pending and pending.get('connection')!=fingerprint(conn):
                raise ContactReviewRequired('The CRM account changed during custom-field creation. Review the previous request.')
            if pending and pending.get('label')==label:
                raise ContactReviewRequired('A custom-field creation may have reached FUB but is not visible yet. Review the field before retrying; another create request was not sent.')
            job.result={**(job.result or {}),'pending_csv_field':{'label':label,'connection':fingerprint(conn)}}
            await checkpoint(db,job)
            await db.execute(select(CrmConnection).where(CrmConnection.id==conn.id,CrmConnection.org_id==conn.org_id).with_for_update())
            await db.refresh(conn)
            if fingerprint(conn)!=job.result['pending_csv_field']['connection']:
                raise ContactReviewRequired('The connected account changed before custom-field creation.')
            fields=await p._custom_fields(http,fresh=True,strict=True)
            existing=[f for f in fields if p._slug(f['label'])==p._slug(label)]
            if len(existing)>1: raise ContactReviewRequired('Custom-field labels are ambiguous. Review them in FUB.')
            field=existing[0] if existing else None
            if field is None and sync.conn_settings(conn).get('csv_create_fields'):
                try:
                    await http.request('POST','/v1/customFields',json={'label':label,'type':'text'})
                except Exception as exc:
                    if getattr(exc,'status',None) not in (401,403): raise
                    create_allowed=False
                    report['warnings'].append('FUB denied custom-field creation; an account-owner API key is required. Unmapped values are retained in the CSV snapshot.')
                else:
                    fields=await p._custom_fields(http,fresh=True,strict=True)
                    existing=[f for f in fields if p._slug(f['label'])==p._slug(label)]
                    if len(existing)!=1: raise ContactReviewRequired('FUB has not confirmed the new custom field. Review it before retrying.')
                    field=existing[0];report['created_fields'].append(field['name'])
            job.result={k:v for k,v in job.result.items() if k!='pending_csv_field'}
            await checkpoint(db,job)
        if field is None:
            report['unmapped'].append(key);continue
        api_key=field['name']
        if not re.fullmatch(r'custom[A-Za-z0-9_]+',api_key):
            report['unmapped'].append(key);continue
        try: converted=convert(value,field)
        except (ValueError,OverflowError):
            report['unmapped'].append(key);continue
        if api_key in plans and plans[api_key][1]!=converted:
            collisions.add(api_key);report['conflicts'].extend([plans[api_key][0],key]);continue
        plans[api_key]=(key,converted)

    # Re-read the latest contact under a lock so cooperating Radar jobs preserve each other's updates.
    lead=await db.scalar(select(Lead).where(Lead.id==lead.id,Lead.org_id==conn.org_id).with_for_update().execution_options(populate_existing=True))
    if lead is None or lead.do_not_call or values_for(lead)!=values:
        raise ContactReviewRequired('The contact data changed during CSV syncing. Review it and retry.')
    await db.refresh(conn)
    if fingerprint(conn)!=account_fingerprint:
        raise ContactReviewRequired('The connected FUB account changed during CSV syncing. Review it before retrying.')
    ref=str((lead.crm_refs or {}).get(conn.provider) or '')
    if not ref.isascii() or not ref.isdigit() or int(ref)<1:
        raise ContactReviewRequired('Link the FUB contact before syncing CSV data.')
    person=await http.request('GET',f'/v1/people/{int(ref)}',params={'fields':'allFields'})
    check_person(person)
    if not same_person(person,*identity(lead)):
        raise ContactReviewRequired('FUB contact identity changed before CSV syncing. Review the link.')
    patch={}
    phone,email=identity(lead)
    # Never replace an existing identifier list. Fill a missing one only after checking uniqueness.
    for kind,value,query_phone,query_email in [('phones',phone,phone,''),('emails',email,'',email)]:
        if not value: continue
        existing=person.get(kind) or []
        source_key='phone' if kind=='phones' else 'email'
        if any(str(x.get('value','')).casefold()==str(value).casefold() for x in existing):
            report['unchanged'].append(source_key)
        elif existing:
            report['conflicts'].append(source_key)
        else:
            match=await find_exact(http,query_phone,query_email)
            if match and str(match['id'])!=ref:
                report['conflicts'].append(source_key)
            else:
                patch[kind]=[{'value':value}];report['synced'].append(source_key)
    for api_key,(key,value) in plans.items():
        if api_key in collisions: continue
        current=person.get(api_key)
        if current in (None,'',[]): patch[api_key]=value;report['synced'].append(key)
        elif confirmed(current,value): report['unchanged'].append(key)
        else: report['conflicts'].append(key)
    if address and 'addresses' not in collisions:
        addresses=person.get('addresses') or []
        current=addresses[0] if addresses else {}
        if any(current.get(part) and str(current[part])!=value for part,value in address.items()):
            report['conflicts'].extend(address_sources.values())
        else:
            merged={**current,**address}
            if merged!=current:
                patch['addresses']=[merged,*addresses[1:]];report['synced'].extend(address_sources.values())
            else: report['unchanged'].extend(address_sources.values())
    background=person.get('background') or ''
    if block not in background:
        patch['background']=background+('\n\n' if background else '')+block
    if patch:
        await http.request('PUT',f'/v1/people/{int(ref)}',json=patch)
        saved=await http.request('GET',f'/v1/people/{int(ref)}',params={'fields':'allFields'})
        if block not in (saved.get('background') or '') or any(not confirmed(saved.get(k),v,k) for k,v in patch.items() if k!='background'):
            raise ContactReviewRequired('FUB did not confirm all CSV updates. Review the contact before retrying.')
    report['snapshot']=True;report['contact_id']=ref
    job.result={**(job.result or {}),'csv_data':report}
    # A previously uncertain field now present in the catalog has been reconciled.
    if (job.result or {}).get('pending_csv_field'):
        pending=job.result['pending_csv_field']
        if pending.get('connection')!=fingerprint(conn) or not any(p._slug(f['label'])==p._slug(pending['label']) for f in fields):
            raise ContactReviewRequired('A previous custom-field creation still requires review.')
        job.result={k:v for k,v in job.result.items() if k!='pending_csv_field'}
    await checkpoint(db,job)
