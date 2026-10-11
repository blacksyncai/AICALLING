# Billing & Usage

Customers manage everything under **Billing & Usage** (`/billing`): Overview, Plans,
Calling Credits, Lead Lookup Balance, and Invoices & Payment Methods. BlackSync admins
use **Admin → Billing** (pricing, Stripe catalog check, payment problems) and the
**Billing** card on each account page (balances, purchases, audit log, lookup-balance
adjustments).

## What's sold

All items live in one place, `backend/app/services/billing/catalog.py`, and each one is
checked against Stripe (amount, currency, one-time vs recurring, active). Nothing is
created in Stripe automatically. A missing item shows as **missing** in Admin → Billing,
where an admin can create it after an explicit confirmation.

| Item | Price | Stripe |
|---|---|---|
| Solo plan | $98 / month, 150 included credits | lookup key `plan_solo_monthly` (or `STRIPE_PRICE_SOLO`) |
| Teams plan | $296 / month, 700 included credits | lookup key `plan_teams_monthly` (or `STRIPE_PRICE_TEAMS`) |
| Quick Top-Up | 100 credits, $29 | `price_1UPKcKR0Rid8tnhHK5Hgkfc5` / `credits_100_one_time` |
| Standard (suggested) | 500 credits, $139 | `price_1UPKcPR0Rid8tnhHKkgMDP69` / `credits_500_one_time` |
| Volume | 1,000 credits, $260 | `price_1UPKcRR0Rid8tnhHrol6d9g3` / `credits_1000_one_time` |
| Lookup funds | $5 / $10 / $25 | `lookup_funds_{5,10,25}_one_time` |
| Additional phone number | $3.50 / month | `additional_phone_number_monthly` (subscription item quantity) |

A subscription on a price that isn't in the catalog (for example an older "Front Desk
Starter" plan) is shown read-only as a custom plan and is never changed by the app.

## Calling credits

- **Lots.** Every grant of credits is a *lot*: included with a plan, purchased,
  auto-recharge, added by BlackSync, or legacy. Each lot records what it cost and when it
  expires. Calls spend included credits first (they expire), then grants, then purchased
  credits (oldest first). Purchased credits never expire. Included credits expire at the
  end of their billing cycle, unless `INCLUDED_CREDITS_ROLLOVER=true`.
- **Rates.** Each LLM model has a rate in credits per connected minute (defaults:
  gpt-4.1-mini, gpt-4.1-nano and gpt-4o-mini 1.0; gpt-4.1 1.4; gpt-4o 1.5). A premium
  (cloned or custom) voice can add a surcharge, which defaults to 0. Admins edit these in
  Admin → Billing. The agent editor shows e.g. "1.4 credits/min • Approx $0.36/min".
- **Billing a call (rounding).** Usage is connected seconds × rate ÷ 60, kept in
  thousandths of a credit. Whole credits are deducted, and the leftover fraction carries
  over to the account's next call, so short calls add up exactly. Every call is billed
  exactly once: `call_usage.call_id` is unique.
- **Never negative.** A call can't take the balance below zero. Anything owed beyond the
  balance is recorded as the call's `shortfall` and shown to admins.
- **Reservations.** Before dialing, the credits a call could use are set aside against
  calls already in flight. The call's maximum length is capped at what the balance
  covers, so a call can't run past what the account can pay for.
- **$ estimate.** The dollar view is an estimate: the weighted average of what the account
  paid for its remaining paid credits, or the lowest list price if it has none. It is
  never a cash wallet.

## Auto-recharge

Auto-recharge is off by default. The customer picks a pack, a threshold (25, 50, 100 or
a custom number) and a monthly spending limit, then ticks an explicit authorization. It
needs a card saved by an earlier purchase.

When the balance drops below the threshold, the saved card is charged off-session with
an idempotency key, and only one recharge per account can be pending. Purchases that
would pass the monthly limit (or the platform cap) are skipped. After 3 failures in a
row auto-recharge turns itself off and a `billing.auto_recharge_failed` webhook event is
sent.

## Lead lookup balance

This is a separate prepaid USD balance, stored in cents, that can only be spent on lead
data. A new single address is paid for in this order:

1. 5 free lookups per account per UTC day (admin setting).
2. Prepaid lookup credits that an admin added earlier.
3. The lookup balance, at the admin-set price per lookup.

Paid lookups are **off until an admin sets a price**. The customer must confirm the
current price before a paid lookup runs; if the price changes, it must be confirmed
again. The money is reserved first, then DataSkip is called, then the charge is settled:

- **"match" policy** (default): only lookups that find an owner are charged.
- **"completed" policy**: every completed lookup is charged.

Failed lookups are always released, and reopening a saved result is always free. Bulk
CSV files skip the free allowance.

## Phone numbers

Billable numbers = max(0, active numbers − included numbers), where included defaults
to 1. They are billed only while the account has a live subscription. The add-on
quantity is updated whenever an admin assigns, buys or releases a number. Released
numbers stop billing from the next invoice (prorated by Stripe). Requests for a number
are never billed.

## Webhooks

The endpoint is `POST https://blacksync.si/api/billing/webhook`. Every event's signature
is verified with `STRIPE_WEBHOOK_SECRET`, and events are deduplicated by event id
(`stripe_events`). The organization always comes from our own records (the purchase row
or the customer mapping), never from browser input.

| Events | Effect |
|---|---|
| `checkout.session.completed` | Grant credits or funds when paid; for subscriptions, mirror the subscription |
| `checkout.session.async_payment_succeeded` / `async_payment_failed` / `expired` | Grant on success; mark failed or canceled otherwise |
| `payment_intent.succeeded` / `payment_intent.payment_failed` | Complete or fail an auto-recharge |
| `customer.subscription.created` / `updated` / `deleted` | Mirror the subscription |
| `invoice.paid` | First and renewal invoices grant included credits (idempotent per invoice); the previous cycle's leftovers expire |
| `invoice.payment_failed` | Logged; the subscription moves to past_due |
| `charge.refunded` | Takes back the unused part of what the refund covered; anything already spent is recorded as `unrecovered` |
| `charge.dispute.created` / `charge.dispute.closed` | Takes back unused credits or funds; restores them if the dispute is won |

Events to enable on the Stripe endpoint: all of the above.

## Environment

| Variable | |
|---|---|
| `STRIPE_SECRET_KEY` | Secret key (backend only; never sent to the browser) |
| `STRIPE_WEBHOOK_SECRET` | Signing secret of the webhook endpoint above |
| `STRIPE_PRICE_SOLO`, `STRIPE_PRICE_TEAMS` | Optional: existing plan price IDs, used if the lookup keys aren't set in Stripe |
| `INCLUDED_CREDITS_ROLLOVER` | Optional, default `false` |
| `APP_URL` | Where Checkout and the portal return to (`https://blacksync.si`) |

## Security

- Card details are handled only by Stripe Checkout and the Billing Portal.
- Every money action requires the account owner or an admin.
- Balances only change through append-only ledgers: `credit_transactions` and
  `lookup_balance_transactions`.
- Admin adjustments write to `billing_audit`: who, which account, previous value, change,
  new value, reason and time.
