# Phone numbers & call recordings

## Phone numbers (per account)

All numbers live in the platform Twilio account, on the Elastic SIP trunk the LiveKit
outbound trunk dials through. Each account gets its own numbers; every outbound call
uses one of them as caller ID (`sip_number` on the SIP participant).

Caller ID order: the agent's **Call from** number → the account's default number →
the trunk's own number (the platform line) if the account has none.

| Action | Who | What happens |
|---|---|---|
| Buy | Admin (account page → Phone numbers → Buy new), or customers when self-serve is on | Twilio purchase with `TrunkSid`, added to the LiveKit trunk's numbers |
| Assign from Twilio | Admin (→ From Twilio) | Number already in Twilio is assigned; its Twilio routing is not changed |
| Request | Customers (Phone Numbers page) when self-serve is off | Shows in Admin → Numbers → Open requests; assigning a number marks it fulfilled |
| Remove | Admin | Bought numbers can be released back to Twilio (stops billing); assigned ones are only unassigned |

Policy (Admin → Numbers): self-serve buying (default **off**), max numbers per account (default 5).
Every admin action is written to `billing_audit`.

### Environment

| Variable | |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID (AC…) |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_TRUNK_SID` | Optional. Blank = matched automatically to the LiveKit trunk's address (`*.pstn.twilio.com`) |

## Call recordings

When a phone call is answered the backend starts a LiveKit **room composite egress**
(audio only, OGG) that uploads to an S3-compatible bucket at
`recordings/<org_id>/<call_id>.ogg`. The call log page plays it through a 15-minute
presigned URL, issued only after the account check. Recording is on per agent by default
(Agent → Actions → Record phone calls). The first second after pickup can be missed while
the egress starts. Check consent rules for the states you call (e.g. two-party consent).

LiveKit Cloud bills egress minutes; the bucket bills storage.

### Environment

| Variable | |
|---|---|
| `RECORDINGS_S3_BUCKET` | Bucket name |
| `RECORDINGS_S3_ACCESS_KEY` / `RECORDINGS_S3_SECRET_KEY` | Bucket credentials |
| `RECORDINGS_S3_ENDPOINT` | Blank for AWS; e.g. `https://storage.railway.app` (Railway Buckets) or an R2 endpoint |
| `RECORDINGS_S3_REGION` | Default `auto` (use the real region on AWS) |
| `RECORDINGS_S3_FORCE_PATH_STYLE` | `true` for providers that need path-style URLs |
