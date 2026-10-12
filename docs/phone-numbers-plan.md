# Plan: every account calls from its own number

## Where things stand

- Per-account numbers already exist: an admin (or the account, if self-serve is on) can buy a Twilio
  number. It's attached to the platform's Elastic SIP trunk and added to the LiveKit outbound trunk's
  caller-ID list. Calls use the agent's chosen number, else the account's default number
  (`telephony.caller_id_for`).
- **The gap:** an account with no number gets `from_number = ""`, so LiveKit dials out with the trunk's
  own number. **Every account without a number shares one caller ID.** That burns the number's
  reputation (spam labels), mixes callbacks between customers, and isn't compliant.
- Self-serve buying is off (`self_serve_numbers = False`), so new accounts usually have no number.
- There's no inbound routing: a callback to an account's number doesn't reach that account's agent.

## Phase 1: stop sharing (about half a day)

1. **No silent fallback.** In `dispatch_call`, refuse phone calls from accounts with no active number,
   with the message "Get a phone number to start calling" (browser tests still work). Admins can still
   use a platform number explicitly through a `house_number` setting for demos.
2. **Auto-provision on signup or plan start.** When a paid plan starts (`included_phone_numbers = 1`),
   buy one local number in the area code picked at onboarding (fallback: the owner's phone area code)
   and make it the default. Free trials get one number too, released after 14 idle days.
3. **Self-serve on, with limits.** Turn on `self_serve_numbers` with `max_numbers_per_org` = 3 for Solo
   and 10 for Teams. Extra numbers use the existing $3.50/mo add-on.
4. **Onboarding step.** Add "Pick your number (area code)" to the getting-started checklist, and show
   the account's caller ID on the agent's Test Call panel.

## Phase 2: deliverability (1–2 days, mostly Twilio console)

- **Trust Hub Business Profile and SHAKEN/STIR:** register the platform's business profile and assign
  every number, so calls get A-level attestation (fewer "Spam Likely" labels).
- **CNAM:** set the caller name per number (the customer's business name, 15 chars) via Twilio
  CNAM registration.
- **Volume guardrails:** cap each number at about 100–150 dials a day and pace calls (already per
  campaign). Warn when an account's answer rate drops sharply, which is a sign the number is flagged.
- **Number health:** a weekly check through a reputation API (e.g. Twilio Voice Integrity / FreeCaller
  Registry) and a "Replace number" button.

## Phase 3: inbound and local presence

- **Inbound:** point each number's voice URL (or the SIP trunk origination) at LiveKit SIP inbound.
  Add a dispatch rule that maps the dialed number to its account's inbound agent (an "Answer calls with"
  agent picker on the number). Unknown callers get created as contacts.
- **Missed-callback handling:** if no inbound agent is set, forward to the account owner's phone or
  play a short message.
- **Local presence (optional):** a pool of numbers per account across area codes, picking the one
  that matches the contact's area code.

## Data and code touch points

- `PhoneNumber` (exists): add `inbound_agent_id`, `cnam`, `daily_dial_count` and `flagged_at`.
- `telephony.caller_id_for`: return a number or raise; no empty string.
- `outbound_call.dispatch_call`: enforce Phase 1 rule 1.
- `billing/subscriptions.py`: provision a number on the first paid period (`included_phone_numbers`).
- LiveKit: one inbound trunk plus a dispatch rule per number (or one rule that reads the dialed number).
