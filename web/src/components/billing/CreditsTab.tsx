"use client";

import { Coins, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Field, Input, Notice, Select, Spinner, Toggle } from "@/components/ui";
import { Card, CardHeader, emptyCls, listCls, rowCls } from "./surface";
import { fetcher, post, put } from "@/lib/api";
import { PillBadge, PricingButton, PricingCard, PricingHeading } from "@/components/ui/pricing";
import { cn } from "@/lib/utils";
import { type AutoRechargeCfg, type Catalog, type CreditBreakdown, type LedgerRow, fmtDate, fmtDateTime, usd } from "./types";
import { CountryPopup } from "./CountryPopup";
import { amount } from "./units";

interface CreditsData extends CreditBreakdown {
  ledger: LedgerRow[];
  usage_by_agent: { agent_id: string | null; agent_name: string; calls: number; minutes: number; credits: number }[];
}

const KIND_LABEL: Record<string, string> = {
  usage: "Call", purchase: "Purchase", included: "Included", grant: "Added by BlackSync", adjustment: "Adjustment",
  expired: "Expired", refund: "Refund", dispute: "Dispute", dispute_won: "Dispute won",
};

export function CreditsTab({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data } = useSWR<CreditsData>("/api/billing/credits", fetcher);
  const { data: cat } = useSWR<Catalog>("/api/billing/catalog", fetcher);
  const [buying, setBuying] = useState<string | null>(null);
  const { data: countryData } = useSWR<{ country: string }>("/api/billing/country", fetcher);
  const [askCountry, setAskCountry] = useState<string | null>(null); // pack waiting on the country pop-up
  const access = cat?.pack_access;
  const packsLocked = !!access && !access.allowed;

  if (!data || !cat)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  async function buy(pack: string, countryOverride?: string) {
    // Ask where they're based the first time; the choice routes Stripe vs Helcim.
    const country = countryOverride ?? countryData?.country;
    if (!country) {
      setAskCountry(pack);
      return;
    }
    setBuying(pack);
    try {
      window.location.href = (await post<{ url: string }>("/api/billing/credits/checkout", { pack })).url;
    } catch (e) {
      toast((e as Error).message, "error");
      setBuying(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card className="rounded-2xl p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Available calling credits</div>
            <div className="mt-1 font-display text-3xl font-semibold tabular-nums tracking-tight">
              {data.unlimited ? "Unlimited" : amount(data.balance)}
            </div>
          </div>
        </div>
        {!data.unlimited && (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Part label="Included with plan" value={amount(data.included)} sub={data.included && data.included_expires_at ? `Expire ${fmtDate(data.included_expires_at)}` : "Used first"} />
            <Part label="Purchased" value={amount(data.purchased)} sub="Never expire" />
            <Part label="Other" value={amount(data.other)} sub="Added by BlackSync" />
          </div>
        )}
      </Card>

      <div>
        <PricingHeading title="Top up your calling credits" description="One-time packs. Purchased credits never expire." />
        {packsLocked ? (
          <div className="mb-4">
            <Notice tone="amber">
              {access?.reason}{" "}
              <Link href="/billing?tab=plans" className="font-semibold underline">
                See plans
              </Link>
            </Notice>
          </div>
        ) : (
          access && !access.on_plan && (
            <p className="mb-4 text-sm text-zinc-500">
              Before you're on a plan, you can buy one credit pack. After that, choose a{" "}
              <Link href="/billing?tab=plans" className="font-medium text-brand-600 hover:text-brand-700">
                BlackSync AI plan
              </Link>{" "}
              to keep topping up.
            </p>
          )
        )}
        <div className="grid gap-4 md:grid-cols-3">
          {cat.packs.map((p, i) => (
            <PricingCard
              key={p.key}
              index={i}
              name={p.name}
              description={`${p.credits.toLocaleString()} AI calling credits`}
              cents={p.amount_cents}
              highlighted={p.suggested}
              badge={p.suggested ? <PillBadge>Popular</PillBadge> : null}
              features={[p.blurb, "Never expire", "Used after your included credits"]}
              footer={
                <PricingButton
                  tone={p.suggested ? "brand" : "dark"}
                  loading={buying === p.key}
                  disabled={!canManage || !p.available || !!buying || packsLocked}
                  onClick={() => void buy(p.key)}
                >
                  {!p.available ? "Not available yet" : packsLocked ? "Plan required" : `Buy ${p.credits.toLocaleString()} credits`}
                </PricingButton>
              }
            />
          ))}
        </div>
        {!canManage && <p className="mt-2 text-xs text-zinc-500">Only account owners and admins can buy credits.</p>}
        <p className="mt-2 text-xs text-zinc-500">
          Calls cost credits per second of connected talk time at each agent&apos;s rate (shown in the agent editor). Fractions of a credit carry over to the next call.
        </p>
      </div>

      <AutoRecharge canManage={canManage} onPlan={access?.on_plan ?? true} packs={cat.packs.filter((p) => p.available)} />
      <CountryPopup
        open={askCountry !== null}
        onDone={(country) => { const pack = askCountry; setAskCountry(null); if (pack) void buy(pack, country); }}
        onCancel={() => setAskCountry(null)}
      />

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card className="min-w-0">
          <CardHeader title="Usage by agent" description="Last 30 days" />
          {data.usage_by_agent.length === 0 ? (
            <p className={emptyCls}>No calls billed yet.</p>
          ) : (
            <ul className={listCls}>
              {data.usage_by_agent.map((u) => (
                <li key={u.agent_id ?? "none"} className={cn("flex items-center justify-between gap-3", rowCls)}>
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-zinc-800">{u.agent_name}</span>
                    <span className="text-xs text-zinc-500">{u.calls} calls · {u.minutes} min</span>
                  </span>
                  <span className="shrink-0 tabular-nums text-zinc-700">{amount(u.credits)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="min-w-0">
          <CardHeader title="Credit history" />
          {data.ledger.length === 0 ? (
            <p className={emptyCls}>No credit activity yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-sm">
                <thead>
                  <tr className="text-left text-xs text-zinc-400">
                    <th className="px-6 py-2.5 font-medium">When</th>
                    <th className="px-3 py-2 font-medium">What</th>
                    <th className="px-3 py-2 text-right font-medium">Change</th>
                    <th className="px-6 py-2.5 text-right font-medium">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ledger.map((t) => (
                    <tr key={t.id} className="transition-colors hover:bg-zinc-50">
                      <td className="whitespace-nowrap px-6 py-2.5 text-xs text-zinc-500">{fmtDateTime(t.created_at)}</td>
                      <td className="px-3 py-2">
                        <span className="text-xs font-medium text-zinc-500">{KIND_LABEL[t.kind] ?? t.kind}</span>
                        <span className="block text-zinc-800">{t.note}</span>
                      </td>
                      <td className={cn("px-3 py-2 text-right font-mono tabular-nums", t.amount > 0 ? "text-emerald-700" : "text-zinc-700")}>
                        {t.amount > 0 ? "+" : ""}
                        {t.amount.toLocaleString(undefined, { maximumFractionDigits: 3 })}
                      </td>
                      <td className="px-6 py-2.5 text-right font-mono tabular-nums text-zinc-500">{t.balance_after.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Part({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl bg-zinc-50 px-4 py-3 ring-1 ring-inset ring-zinc-100">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-0.5 font-semibold tabular-nums text-zinc-900">{value}</div>
      <div className="text-[11px] text-zinc-400">{sub}</div>
    </div>
  );
}

const THRESHOLDS = [25, 50, 100];

function AutoRecharge({ canManage, onPlan, packs }: { canManage: boolean; onPlan: boolean; packs: Catalog["packs"] }) {
  const toast = useToast();
  const { data, mutate } = useSWR<AutoRechargeCfg>("/api/billing/auto-recharge", fetcher);
  const [form, setForm] = useState<{ pack_key: string; threshold: string; custom: boolean; limit: string; consent: boolean } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data && !form)
      setForm({
        pack_key: data.pack_key, threshold: String(data.threshold), custom: !THRESHOLDS.includes(data.threshold),
        limit: String(Math.round(data.monthly_limit_cents / 100)), consent: false,
      });
  }, [data, form]);

  if (!data || !form) return null;
  const pack = packs.find((p) => p.key === form.pack_key);

  if (!onPlan && !data.enabled)
    return (
      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2"><RefreshCw className="h-4 w-4 text-zinc-400" /> Auto-recharge</span>}
          description="Automatically buy a credit pack when your balance runs low, so calls never stop."
          action={<Badge tone="gray">Plans only</Badge>}
        />
        <p className="px-5 pb-5 text-sm text-zinc-500">
          Auto-recharge is available on BlackSync AI plans.{" "}
          <Link href="/billing?tab=plans" className="font-medium text-brand-600 hover:text-brand-700">
            See plans
          </Link>
        </p>
      </Card>
    );

  async function save(enabled: boolean) {
    if (!form) return;
    setSaving(true);
    try {
      await put("/api/billing/auto-recharge", {
        enabled, pack_key: form.pack_key, threshold: Number(form.threshold),
        monthly_limit_cents: Math.round(Number(form.limit) * 100), consent: form.consent,
      });
      await mutate();
      setForm((f) => (f ? { ...f, consent: false } : f));
      toast(enabled ? "Auto-recharge is on" : "Auto-recharge is off");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2"><RefreshCw className="h-4 w-4 text-zinc-400" /> Auto-recharge</span>}
        description="Automatically buy a credit pack when your balance runs low, so calls never stop."
        action={<Badge tone={data.enabled ? "green" : "gray"}>{data.enabled ? "On" : "Off"}</Badge>}
      />
      <div className="flex flex-col gap-4 p-5">
        {data.last_error && <Notice tone={data.enabled ? "amber" : "red"}>{data.last_error}</Notice>}
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Pack to buy">
            <Select value={form.pack_key} onChange={(e) => setForm({ ...form, pack_key: e.target.value })} disabled={!canManage}>
              {packs.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name} — {p.credits.toLocaleString()} credits for {usd(p.amount_cents, 0)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="When credits fall below">
            <div className="flex gap-2">
              <Select
                value={form.custom ? "custom" : form.threshold}
                onChange={(e) => setForm(e.target.value === "custom" ? { ...form, custom: true } : { ...form, custom: false, threshold: e.target.value })}
                disabled={!canManage}
              >
                {THRESHOLDS.map((t) => (
                  <option key={t} value={t}>
                    {t} credits
                  </option>
                ))}
                <option value="custom">Custom…</option>
              </Select>
              {form.custom && (
                <Input className="w-24" inputMode="numeric" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value.replace(/\D/g, "") })} disabled={!canManage} />
              )}
            </div>
          </Field>
          <Field label="Monthly spending limit ($)" hint={`${usd(data.month_to_date_cents)} spent on auto-recharge this month`}>
            <Input inputMode="numeric" value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value.replace(/[^\d]/g, "") })} disabled={!canManage} />
          </Field>
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Coins className="h-3.5 w-3.5" />
          {data.card ? `Charges your saved ${data.card.brand ?? "card"} ending ${data.card.last4}.` : "No saved card yet — buy any credit pack once and your card is saved for auto-recharge."}
        </div>
        {canManage && (
          <>
            {!data.enabled && (
              <Toggle
                checked={form.consent}
                onChange={(v) => setForm({ ...form, consent: v })}
                label="I authorize automatic charges"
                description={
                  pack
                    ? `BlackSync will charge ${usd(pack.amount_cents)} to my saved card for ${pack.credits.toLocaleString()} credits each time my balance drops below ${form.threshold || "—"} credits, up to $${form.limit || 0} per calendar month, until I turn this off.`
                    : "Choose a pack first."
                }
              />
            )}
            <div className="flex flex-wrap gap-2">
              {data.enabled ? (
                <>
                  <Button className="rounded-full!" variant="primary" loading={saving} onClick={() => void save(true)} disabled={!form.consent}>
                    Save changes
                  </Button>
                  <Button className="rounded-full!" loading={saving} onClick={() => void save(false)}>
                    Turn off
                  </Button>
                  {!form.consent && <span className="self-center text-xs text-zinc-500">Changing settings needs your authorization again — tick below.</span>}
                </>
              ) : (
                <Button className="rounded-full!" variant="primary" loading={saving} onClick={() => void save(true)} disabled={!form.consent || !data.card}>
                  Turn on auto-recharge
                </Button>
              )}
            </div>
            {data.enabled && (
              <Toggle
                checked={form.consent}
                onChange={(v) => setForm({ ...form, consent: v })}
                label="I authorize automatic charges with these settings"
              />
            )}
          </>
        )}
      </div>
    </Card>
  );
}
