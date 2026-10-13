"use client";

import { Bot, Headset, Phone, Plug, Users } from "lucide-react";
import type { ReactNode } from "react";
import { PillBadge, PricingButton, PricingCard } from "@/components/ui/pricing";
import { cn } from "@/lib/utils";
import type { Plan } from "./types";

const n = (v: number | null, one: string, many: string) => (v == null ? `Unlimited ${many}` : `${v} ${v === 1 ? one : many}`);

function Facts({ plan, dark }: { plan: Plan; dark: boolean }) {
  const l = plan.limits;
  const rows: [ReactNode, string][] = [
    [<Bot key="a" className="h-4 w-4" />, n(l.agents, "AI agent", "AI agents")],
    [<Users key="u" className="h-4 w-4" />, l.seats === 1 ? "1 user" : n(l.seats, "user", "users")],
    [<Phone key="p" className="h-4 w-4" />, `${n(l.numbers, "phone number", "phone numbers")} included`],
    [<Plug key="c" className="h-4 w-4" />, l.crm === 0 ? "No CRM integrations" : l.crm == null ? "Multiple CRMs" : n(l.crm, "CRM integration", "CRM integrations")],
    [<Headset key="s" className="h-4 w-4" />, plan.support],
  ];
  return (
    <ul className={cn("grid gap-2 rounded-2xl p-3.5 text-[13px]", dark ? "bg-white/5 text-zinc-200 ring-1 ring-white/10" : "bg-zinc-50 text-zinc-700 ring-1 ring-zinc-900/5")}>
      {rows.map(([icon, text]) => (
        <li key={text} className="flex items-center gap-2.5">
          <span className={dark ? "text-brand-300" : "text-brand-600"}>{icon}</span>
          {text}
        </li>
      ))}
    </ul>
  );
}

export interface PlanAction {
  label: string;
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
  loading?: boolean;
  muted?: boolean;
}

/** The four plan cards (Solo, Growth, Teams, Managed) — used in Billing and on the public pricing page. */
export function PlanCards({ plans, currentKey, action, focus }: {
  plans: Plan[];
  currentKey?: string | null;
  action: (p: Plan) => PlanAction;
  focus?: string | null;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {plans.map((p, i) => {
        const current = currentKey === p.key;
        const dark = !!p.recommended;
        const managed = !p.self_serve;
        const a = action(p);
        const button = (
          <PricingButton tone={a.muted ? "muted" : dark ? "brand" : "dark"} loading={a.loading} disabled={a.disabled} onClick={a.onClick}>
            {a.label}
          </PricingButton>
        );
        return (
          <div key={p.key} id={`plan-${p.key}`} className={cn("rounded-3xl", focus === p.key && "ring-2 ring-brand-500 ring-offset-4 ring-offset-transparent")}>
            <PricingCard
              index={i}
              name={p.name}
              description={p.tagline}
              cents={p.amount_cents ?? 0}
              period={p.interval}
              pricePrefix={p.quote_label ? undefined : p.starting_at ? "Starting at" : undefined}
              priceLabel={p.quote_label}
              sub={p.quote_note ?? `${p.included_credits.toLocaleString()} calling credits / month`}
              variant={dark ? "dark" : "light"}
              highlighted={current && !dark}
              badge={
                current ? (
                  <PillBadge tone={dark ? "light" : "dark"}>Current plan</PillBadge>
                ) : dark ? (
                  <PillBadge>Most popular</PillBadge>
                ) : managed ? (
                  <PillBadge tone="dark">White-glove</PillBadge>
                ) : null
              }
              footer={
                a.href ? (
                  <a href={a.href} target="_blank" rel="noreferrer" className="block">
                    {button}
                  </a>
                ) : (
                  button
                )
              }
              facts={<Facts plan={p} dark={dark} />}
              featuresTitle={p.features_title}
              features={[...p.features, ...(p.scope_note ? [<span key="scope" className="text-zinc-500">{p.scope_note}</span>] : [])]}
            />
          </div>
        );
      })}
    </div>
  );
}
