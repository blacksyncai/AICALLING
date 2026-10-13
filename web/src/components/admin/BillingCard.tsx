"use client";

import { useState } from "react";
import useSWR from "swr";
import { usd, fmtDate, fmtDateTime } from "@/components/billing/types";
import { Badge, Button, Card, CardHeader, Field, Input, Spinner } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher, post } from "@/lib/api";

interface OrgBilling {
  plan: { status: string; name: string | null; plan_key: string | null; current_period_end: string | null; cancel_at_period_end?: boolean };
  credits: { balance: number; included: number; purchased: number; other: number; cents_per_credit: number; unlimited: boolean };
  lookups: { balance_cents: number; prepaid_credits: number; free_remaining: number; free_daily: number; price_cents: number | null };
  phones: { active: number; included: number; billable: number; billed_quantity: number };
  usage_30d: { calls: number; minutes: number; credits: number; shortfall: number; lookup_spend_cents: number };
  purchases: { id: string; kind: string; amount_cents: number; credits: number; status: string; created_at: string | null; refunded_cents: number }[];
  auto_recharge: { enabled: boolean; threshold: number; pack_key: string; last_error: string | null; month_to_date_cents: number } | null;
  audit: { target: string; previous: string; adjustment: string; new: string; reason: string; at: string | null }[];
  stripe_customer: string | null;
}

const TARGET: Record<string, string> = {
  calling_credits: "Calling credits", lookup_balance: "Lookup balance", phone_numbers: "Phone numbers", pricing: "Pricing",
  entitlements: "Entitlements", managed: "Managed plan", quote: "Quote",
};

/** Admin: one account's subscription, balances, purchases, usage and the audit trail, plus lookup-balance adjustments. */
export function BillingCard({ orgId }: { orgId: string }) {
  const toast = useToast();
  const url = `/api/admin/billing/orgs/${orgId}`;
  const { data, mutate } = useSWR<OrgBilling>(url, fetcher);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function adjust(sign: 1 | -1) {
    const dollars = Number(amount);
    if (!(dollars > 0)) return toast("Enter a dollar amount.", "error");
    if (reason.trim().length < 3) return toast("Add a reason — it's saved in the audit log.", "error");
    setBusy(true);
    try {
      const r = await post<{ balance_cents: number }>(`/api/admin/orgs/${orgId}/lookup-balance`, {
        amount_cents: sign * Math.round(dollars * 100), reason: reason.trim(),
      });
      setAmount("");
      setReason("");
      await mutate();
      toast(`Lookup balance: ${usd(r.balance_cents)}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="min-w-0">
      <CardHeader title="Billing" description={data?.stripe_customer ? `Stripe customer ${data.stripe_customer}` : "No Stripe customer yet"} />
      {!data ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="flex flex-col gap-5 p-5 text-sm">
          <dl className="grid grid-cols-2 gap-3">
            <Item label="Plan" value={data.plan.status === "none" ? "None" : data.plan.name ?? "—"}
                  sub={data.plan.status === "none" ? undefined : `${data.plan.status}${data.plan.cancel_at_period_end ? " · ending" : ""} · ${fmtDate(data.plan.current_period_end)}`} />
            <Item label="Calling credits" value={data.credits.unlimited ? "Unlimited" : data.credits.balance.toLocaleString()}
                  sub={`${data.credits.included} included · ${data.credits.purchased} bought · ${data.credits.other} other`} />
            <Item label="Lookup balance" value={usd(data.lookups.balance_cents)}
                  sub={`${data.lookups.prepaid_credits} prepaid · ${data.lookups.free_remaining}/${data.lookups.free_daily} free today`} />
            <Item label="Phone numbers" value={String(data.phones.active)} sub={`${data.phones.included} included · ${data.phones.billed_quantity} billed`} />
            <Item label="Last 30 days" value={`${data.usage_30d.calls} calls`}
                  sub={`${data.usage_30d.minutes} min · ${data.usage_30d.credits} credits${data.usage_30d.shortfall ? ` · ${data.usage_30d.shortfall} unpaid` : ""}`} />
            <Item label="Lookup spend (30d)" value={usd(data.usage_30d.lookup_spend_cents)}
                  sub={data.auto_recharge?.enabled ? `Auto-recharge on (${usd(data.auto_recharge.month_to_date_cents)} this month)` : "Auto-recharge off"} />
          </dl>

          <div>
            <div className="mb-2 text-xs font-medium text-zinc-700">Adjust lookup balance</div>
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Amount ($)" className="w-28">
                <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} placeholder="10" />
              </Field>
              <Field label="Reason (audited)" className="min-w-40 flex-1">
                <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Goodwill credit" />
              </Field>
              <Button variant="primary" onClick={() => void adjust(1)} loading={busy}>
                Add
              </Button>
              <Button onClick={() => void adjust(-1)} disabled={busy}>
                Remove
              </Button>
            </div>
          </div>

          {data.purchases.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-medium text-zinc-700">Purchases</div>
              <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
                {data.purchases.slice(0, 8).map((p) => (
                  <li key={p.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                    <span className="min-w-0 flex-1 truncate">
                      {p.kind.replace("_", " ")}
                      {p.credits ? ` · ${p.credits} credits` : ""} · {fmtDateTime(p.created_at)}
                    </span>
                    <Badge tone={p.status === "paid" ? "green" : p.status === "failed" || p.status === "disputed" ? "red" : "gray"}>{p.status}</Badge>
                    <span className="w-16 text-right tabular-nums">{usd(p.amount_cents)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <div className="mb-2 text-xs font-medium text-zinc-700">Audit log</div>
            {data.audit.length === 0 ? (
              <p className="text-xs text-zinc-500">No manual changes yet.</p>
            ) : (
              <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
                {data.audit.slice(0, 10).map((a, i) => (
                  <li key={i} className="px-3 py-2 text-xs">
                    <div className="flex justify-between gap-2">
                      <span className="font-medium text-zinc-800">{TARGET[a.target] ?? a.target}</span>
                      <span className="text-zinc-400">{fmtDateTime(a.at)}</span>
                    </div>
                    <div className="text-zinc-600">
                      {a.previous && `${a.previous} → `}
                      {a.new} ({a.adjustment}) · {a.reason}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function Item({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-zinc-50 px-3 py-2">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="font-semibold tabular-nums text-zinc-900">{value}</dd>
      {sub && <dd className="text-[11px] text-zinc-500">{sub}</dd>}
    </div>
  );
}
