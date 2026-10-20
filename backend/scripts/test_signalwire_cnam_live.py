"""Opt-in REAL SignalWire integration test; never run automatically in CI.

Uses the existing SIGNALWIRE_* config. Read-only unless --submit and both explicit
operator authorization flags are present. Saves receipts without credentials.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.number_registration.signalwire import Client, ProviderError, normalize_name


async def run(args):
    if not re.fullmatch(r'\+[1-9]\d{7,14}', args.number): raise ValueError('An actual E.164 number is required.')
    name = normalize_name(args.caller_name)
    if args.submit and not (args.authorize_registration and args.authorize_carrier_fees):
        raise ValueError('Live submission requires explicit registration and possible carrier fee authorization.')
    receipt_path = Path(args.receipts)
    records = []
    async def receipt(method,path,status,body,request_id):
        records.append({'at':datetime.now(timezone.utc).isoformat(),'method':method,'path':path,
                        'http_status':status,'request_id':request_id,'response':body})
        fd=os.open(str(receipt_path),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:json.dump(records,f,indent=2)
    client = Client(receipt=receipt)
    phone = await client.number(args.number_id)
    if phone.get('number') != args.number:raise ValueError('Carrier ID does not belong to the authorized test number.')
    latest = await client.latest(args.number_id)
    if latest and latest.get('name') != name:raise ValueError('A different CNAM request exists; no changes made.')
    if args.submit and not latest:latest=await client.submit(args.number_id,name)
    if not latest:
        print(json.dumps({'result':'no_existing_request','submission_performed':False}));return
    for index in range(args.polls+1):
        latest=await client.latest(args.number_id)
        phone=await client.number(args.number_id)
        status=(latest or {}).get('status')
        active=bool(latest and latest.get('name')==name and status=='approved' and phone.get('cnam')==name)
        print(json.dumps({'request_id':(latest or {}).get('id'),'provider_status':status,'activation_confirmed':active}),flush=True)
        if active or status in ('rejected','failed') or index==args.polls:return
        await asyncio.sleep(args.interval)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--number-id',required=True);p.add_argument('--number',required=True)
    p.add_argument('--caller-name',required=True);p.add_argument('--receipts',required=True)
    p.add_argument('--submit',action='store_true');p.add_argument('--authorize-registration',action='store_true')
    p.add_argument('--authorize-carrier-fees',action='store_true');p.add_argument('--polls',type=int,default=0)
    p.add_argument('--interval',type=int,default=60)
    args=p.parse_args()
    if not 0<=args.polls<=100 or args.interval<15:p.error('Polls must be 0–100 and interval at least 15 seconds.')
    try:asyncio.run(run(args))
    except (ProviderError,ValueError) as exc:sys.exit(str(exc))
