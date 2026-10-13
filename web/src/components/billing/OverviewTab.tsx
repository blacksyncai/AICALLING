"use client";

import { Coins, CreditCard, Hash, UserSearch } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui";
import { Card, CardHeader, PillAction, emptyCls, listCls, rowCls } from "./surface";
import { cn } from "@/lib/utils";
import { type Overview, fmtDate, fmtDateTime, usd } from "./types";
import { amount } from "./units";

type Go = (tab: "overview" | "plans" | "credits" | "lookups" | "invoices") => void;

function SummaryCard({ icon, title, value, sub, action, children }: {
  icon: ReactNode; title: string; value: ReactNode; sub?: ReactNode; action?: { label: string; onClick: () => void }; children?: ReactNode;
}) {
  return (
    <Card className="flex min-w-0 flex-col p-6">
      <div className="flex items-center gap-2 text-sm font-medium text-zinc-500">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-50 text-brand-600">{icon}</span>
        {title}
      </div>
      <div className="mt-4 font-display text-3xl font-semibold tabular-nums tracking-tight text-zinc-900">{value}</div>
      {sub && <div className="mt-1.5 text-xs text-zinc-500">{sub}</div>}
      {children}
      {action && (
        <div className="mt-auto pt-5">
          <PillAction onClick={action.onClick} tone="light">
            {action.label}
          </PillAction>
        </div>
      )}
    </Card>
  );
}

const STATUS_TONE: Record<string, "green" | "amber" | "red" | "gray"> = {
  active: "green", trialing: "green", past_due: "amber", incomplete: "amber", unpaid: "red", canceled: "gray", none: "gray",
};

export function OverviewTab({ overview: o, go }: { overview: Overview; go: Go }) {
  const c = o.credits;
  const plan = o.plan;
  const planCents = plan.status !== "none" && plan.status !== "canceled" ? plan.amount_cents ?? 0 : 0;
  const phonesCents = o.phones.billed_quantity * o.phones.unit_cents;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 md:grid-cols-3">
        <SummaryCard
          icon={<CreditCard className="h-4 w-4" />}
          title="Plan"
          value={plan.status === "none" ? "No plan" : plan.name}
          sub={
            plan.status === "none" ? (
              "Pay as you go with credit packs"
            ) : (
              <span className="flex flex-wrap items-center gap-1.5">
                <Badge tone={STATUS_TONE[plan.status] ?? "gray"}>{plan.status.replace("_", " ")}</Badge>
                {plan.cancel_at_period_end ? `Ends ${fmtDate(plan.current_period_end)}` : plan.current_period_end ? `Renews ${fmtDate(plan.current_period_end)}` : null}
              </span>
            )
          }
          action={{ label: plan.status === "none" ? "See plans" : "Manage plan", onClick: () => go("plans") }}
        />
        <SummaryCard
          icon={<Coins className="h-4 w-4" />}
          title="Calling credits"
          value={c.unlimited ? "Unlimited" : amount(c.balance)}
          sub={
            c.unlimited
              ? "This account isn't charged for calls"
              : `${c.used_30d.toLocaleString()} used in the last 30 days · ${c.minutes_30d.toLocaleString()} min`
          }
          action={{ label: "Buy credits", onClick: () => go("credits") }}
        >
        </SummaryCard>
        <SummaryCard
          icon={<UserSearch className="h-4 w-4" />}
          title="Lead lookup balance"
          value={o.lookups.unlimited ? "Unlimited" : usd(o.lookups.balance_cents)}
          sub={`${o.lookups.free_remaining} of ${o.lookups.free_daily} free lookups left today` +
            (o.lookups.prepaid_credits ? ` · ${o.lookups.prepaid_credits} prepaid lookups` : "")}
          action={{ label: "Add funds", onClick: () => go("lookups") }}
        />
      </div>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card className="min-w-0">
          <CardHeader title="Subscription breakdown" description="What renews each month" />
          <dl className={listCls}>
            <Row label={plan.status === "none" ? "Plan" : `${plan.name} plan`} value={plan.status === "none" ? "—" : planCents ? usd(planCents) : "Custom"} />
            {plan.included_credits ? <Row label="Included credits" value={`${plan.included_credits.toLocaleString()} / month`} /> : null}
            <Row
              label={<span className="flex items-center gap-1.5"><Hash className="h-3.5 w-3.5 text-zinc-400" /> Phone numbers</span>}
              value={
                o.phones.active === 0
                  ? "None"
                  : `${o.phones.active} active · ${o.phones.included} included${o.phones.billable ? ` · ${o.phones.billable} × ${usd(o.phones.unit_cents)}` : ""}`
              }
            />
            {phonesCents > 0 && <Row label="Additional numbers" value={usd(phonesCents)} />}
            <div className="my-1 flex items-center justify-between gap-4 rounded-xl bg-zinc-50 px-3 py-3">
              <dt className="font-medium text-zinc-900">Monthly total</dt>
              <dd className="font-display text-lg font-semibold tabular-nums text-zinc-900">{usd(planCents + phonesCents)}</dd>
            </div>
            <Row
              label="Auto-recharge"
              value={o.auto_recharge.enabled ? `On — below ${o.auto_recharge.threshold} credits` : "Off"}
              tone={o.auto_recharge.last_error ? "amber" : undefined}
            />
          </dl>
          {o.auto_recharge.last_error && <p className="px-6 pb-5 text-xs text-amber-700">{o.auto_recharge.last_error}</p>}
        </Card>

        <Card className="min-w-0">
          <CardHeader title="Recent activity" />
          {o.activity.length === 0 ? (
            <p className={emptyCls}>No billing activity yet.</p>
          ) : (
            <ul className={listCls}>
              {o.activity.map((a) => {
                const value = a.type === "credits" ? a.amount ?? 0 : a.amount_cents ?? 0;
                const positive = value > 0;
                return (
                  <li key={`${a.type}-${a.id}`} className={cn("flex items-center gap-3", rowCls)}>
                    <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", a.type === "credits" ? "bg-brand-50 text-brand-600" : "bg-sky-50 text-sky-600")}>
                      {a.type === "credits" ? <Coins className="h-3.5 w-3.5" /> : <UserSearch className="h-3.5 w-3.5" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-zinc-800">{a.note || a.kind}</span>
                      <span className="text-xs text-zinc-400">{fmtDateTime(a.created_at)}</span>
                    </span>
                    <span className={cn("shrink-0 font-mono text-sm tabular-nums", positive ? "text-emerald-700" : "text-zinc-700")}>
                      {positive ? "+" : ""}
                      {a.type === "credits" ? value.toLocaleString() : usd(value)}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value, tone }: { label: ReactNode; value: ReactNode; tone?: "amber" }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl px-3 py-2.5">
      <dt className="text-zinc-500">{label}</dt>
      <dd className={cn("text-right tabular-nums text-zinc-800", tone === "amber" && "text-amber-700")}>{value}</dd>
    </div>
  );
}
