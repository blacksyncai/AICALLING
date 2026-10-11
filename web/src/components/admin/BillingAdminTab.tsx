"use client";

import { CheckCircle2, CircleAlert, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { usd, fmtDateTime } from "@/components/billing/types";
import { Badge, Button, Card, CardHeader, Field, Input, Notice, Select, Spinner } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher, patch, post } from "@/lib/api";

interface BillingSettings {
  property_lookup_price_cents: number | null;
  lookup_charge_policy: "match" | "completed";
  lookup_free_daily: number;
  model_credit_rates: Record<string, number>;
  premium_voice_surcharge: number;
  included_phone_numbers: number;
  auto_recharge_max_monthly_cents: number;
  stripe_ready: boolean;
  webhook_ready: boolean;
  included_credits_rollover: boolean;
}

interface CatalogItem {
  kind: string;
  key: string;
  name: string;
  amount_cents: number;
  lookup_key: string;
  type: string;
  price_id: string | null;
  status: "ok" | "missing" | "mismatch" | "unconfigured";
  detail: string;
}

interface Failures {
  webhook_failures: { id: string; type: string; error: string | null; at: string | null }[];
  payment_failures: { id: string; org_id: string; org_name: string; kind: string; amount_cents: number; error: string | null; at: string | null }[];
  auto_recharge_errors: { org_id: string; org_name: string; error: string | null; failures: number; enabled: boolean }[];
}

const STATUS_TONE = { ok: "green", missing: "red", mismatch: "amber", unconfigured: "gray" } as const;

/** Admin portal → Billing: pricing & policies, the Stripe catalog check, and payment/webhook failures. */
export function BillingAdminTab() {
  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-2">
      <div className="flex min-w-0 flex-col gap-6">
        <PricingCard />
      </div>
      <div className="flex min-w-0 flex-col gap-6">
        <CatalogCard />
        <FailuresCard />
      </div>
    </div>
  );
}

function PricingCard() {
  const toast = useToast();
  const { data, mutate } = useSWR<BillingSettings>("/api/admin/billing/settings", fetcher);
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data && !form)
      setForm({
        price: data.property_lookup_price_cents == null ? "" : (data.property_lookup_price_cents / 100).toFixed(2),
        policy: data.lookup_charge_policy,
        free: String(data.lookup_free_daily),
        surcharge: String(data.premium_voice_surcharge),
        phones: String(data.included_phone_numbers),
        cap: String(Math.round(data.auto_recharge_max_monthly_cents / 100)),
        ...Object.fromEntries(Object.entries(data.model_credit_rates).map(([k, v]) => [`rate:${k}`, String(v)])),
      });
  }, [data, form]);

  if (!data || !form)
    return (
      <Card className="flex justify-center py-10">
        <Spinner />
      </Card>
    );

  const set = (k: string, v: string) => setForm({ ...form, [k]: v });

  async function save() {
    if (!form || !data) return;
    const price = form.price.trim();
    if (price && !(Number(price) > 0)) return toast("Enter a lookup price above $0, or leave it empty to keep paid lookups off.", "error");
    if (price && Number(price) * 100 !== (data.property_lookup_price_cents ?? 0) &&
        !window.confirm(`Set paid lookups to $${Number(price).toFixed(2)} each? Customers see this price and confirm it before every paid lookup.`)) return;
    setSaving(true);
    try {
      const rates = Object.fromEntries(Object.entries(form).filter(([k]) => k.startsWith("rate:")).map(([k, v]) => [k.slice(5), Number(v)]));
      await patch("/api/admin/billing/settings", {
        ...(price ? { property_lookup_price_cents: Math.round(Number(price) * 100) } : { clear_lookup_price: true }),
        lookup_charge_policy: form.policy,
        lookup_free_daily: Number(form.free),
        premium_voice_surcharge: Number(form.surcharge),
        included_phone_numbers: Number(form.phones),
        auto_recharge_max_monthly_cents: Math.round(Number(form.cap) * 100),
        model_credit_rates: rates,
        reason: "Updated from admin portal",
      });
      await mutate();
      setForm(null);
      toast("Billing settings saved");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Pricing & policies" description="Every change is saved to the audit log" />
      <div className="flex flex-col gap-5 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Paid lookup price ($)" hint={data.property_lookup_price_cents == null ? "Empty = paid lookups off" : "Leave empty to turn paid lookups off"}>
            <Input inputMode="decimal" value={form.price} onChange={(e) => set("price", e.target.value.replace(/[^\d.]/g, ""))} placeholder="Not set" />
          </Field>
          <Field label="Charge lookups">
            <Select value={form.policy} onChange={(e) => set("policy", e.target.value)}>
              <option value="match">Only when an owner is found</option>
              <option value="completed">Every completed lookup</option>
            </Select>
          </Field>
          <Field label="Free single lookups / day">
            <Input inputMode="numeric" value={form.free} onChange={(e) => set("free", e.target.value.replace(/\D/g, ""))} />
          </Field>
          <Field label="Phone numbers included with a plan">
            <Input inputMode="numeric" value={form.phones} onChange={(e) => set("phones", e.target.value.replace(/\D/g, ""))} />
          </Field>
          <Field label="Premium voice surcharge (credits/min)">
            <Input inputMode="decimal" value={form.surcharge} onChange={(e) => set("surcharge", e.target.value.replace(/[^\d.]/g, ""))} />
          </Field>
          <Field label="Auto-recharge monthly cap ($)">
            <Input inputMode="numeric" value={form.cap} onChange={(e) => set("cap", e.target.value.replace(/\D/g, ""))} />
          </Field>
        </div>
        <div>
          <div className="mb-2 text-xs font-medium text-zinc-700">Credits per connected minute, by model</div>
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.keys(data.model_credit_rates).map((m) => (
              <label key={m} className="flex items-center justify-between gap-2 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm">
                <span className="whitespace-nowrap font-mono text-xs text-zinc-600">{m}</span>
                <span className="w-16 shrink-0">
                  <Input className="h-8 text-right" inputMode="decimal" value={form[`rate:${m}`]} onChange={(e) => set(`rate:${m}`, e.target.value.replace(/[^\d.]/g, ""))} aria-label={`${m} credits per minute`} />
                </span>
              </label>
            ))}
          </div>
        </div>
        <p className="text-xs text-zinc-500">
          Included credits {data.included_credits_rollover ? "roll over" : "expire at the end of each billing cycle"} (INCLUDED_CREDITS_ROLLOVER).
        </p>
        <div className="flex justify-end">
          <Button variant="primary" loading={saving} onClick={() => void save()}>
            Save settings
          </Button>
        </div>
      </div>
    </Card>
  );
}

function CatalogCard() {
  const toast = useToast();
  const { data, mutate, isValidating } = useSWR<{ stripe_ready: boolean; items: CatalogItem[] }>("/api/admin/billing/catalog", fetcher);
  const [creating, setCreating] = useState<string | null>(null);
  const { data: settings } = useSWR<BillingSettings>("/api/admin/billing/settings", fetcher);

  async function create(item: CatalogItem) {
    if (!window.confirm(`Create "${item.name}" in your LIVE Stripe account at ${usd(item.amount_cents)}${item.type === "recurring" ? "/month" : ""} with lookup key ${item.lookup_key}?\n\nOnly do this if it doesn't already exist under another name.`)) return;
    setCreating(item.key);
    try {
      await post(`/api/admin/billing/catalog/${item.key}/create`, { confirm: true });
      await mutate();
      toast("Created in Stripe");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setCreating(null);
    }
  }

  return (
    <Card className="min-w-0">
      <CardHeader
        title="Stripe catalog"
        description="Each item checked against Stripe (amount, currency, type, active)"
        action={
          <Button size="sm" variant="ghost" onClick={() => void mutate()} loading={isValidating}>
            <RefreshCw className="h-3.5 w-3.5" /> Recheck
          </Button>
        }
      />
      {settings && (
        <div className="flex flex-wrap gap-4 border-b border-zinc-100 px-5 py-3 text-xs">
          <Status ok={settings.stripe_ready} label={settings.stripe_ready ? "Stripe connected" : "STRIPE_SECRET_KEY not set"} />
          <Status ok={settings.webhook_ready} label={settings.webhook_ready ? "Webhook secret set" : "STRIPE_WEBHOOK_SECRET not set"} />
        </div>
      )}
      {!data ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <ul className="divide-y divide-zinc-100">
          {data.items.map((i) => (
            <li key={i.key} className="flex flex-wrap items-center gap-2 px-5 py-2.5 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-zinc-800">
                  {i.name} <span className="font-normal text-zinc-500">· {usd(i.amount_cents)}{i.type === "recurring" ? "/mo" : ""}</span>
                </span>
                <span className="block truncate text-xs text-zinc-500">{i.price_id ?? i.lookup_key} — {i.detail}</span>
              </span>
              <Badge tone={STATUS_TONE[i.status]}>{i.status}</Badge>
              {i.status === "missing" && data.stripe_ready && (
                <Button size="sm" onClick={() => void create(i)} loading={creating === i.key}>
                  Create in Stripe
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function FailuresCard() {
  const { data } = useSWR<Failures>("/api/admin/billing/failures", fetcher, { refreshInterval: 60000 });
  if (!data) return null;
  const none = !data.webhook_failures.length && !data.payment_failures.length && !data.auto_recharge_errors.length;
  return (
    <Card className="min-w-0">
      <CardHeader title="Payment problems" description="Failed payments, auto-recharge errors and webhook failures" />
      {none ? (
        <p className="px-5 py-4 text-sm text-zinc-500">Nothing needs attention.</p>
      ) : (
        <div className="flex flex-col gap-3 p-5 text-sm">
          {data.payment_failures.map((p) => (
            <Notice key={p.id} tone="red">
              <Link href={`/admin/accounts/${p.org_id}`} className="font-medium underline">{p.org_name}</Link> — {p.kind.replace("_", " ")} {usd(p.amount_cents)} failed
              {p.error ? `: ${p.error}` : ""} ({fmtDateTime(p.at)})
            </Notice>
          ))}
          {data.auto_recharge_errors.map((r) => (
            <Notice key={r.org_id} tone="amber">
              <Link href={`/admin/accounts/${r.org_id}`} className="font-medium underline">{r.org_name}</Link> auto-recharge: {r.error}
              {!r.enabled ? " (turned off)" : ""}
            </Notice>
          ))}
          {data.webhook_failures.map((w) => (
            <Notice key={w.id} tone="red">
              Webhook {w.type} ({w.id}) failed: {w.error} — Stripe retries automatically. {fmtDateTime(w.at)}
            </Notice>
          ))}
        </div>
      )}
    </Card>
  );
}

function Status({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      {ok ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <CircleAlert className="h-3.5 w-3.5 text-amber-500" />}
      {label}
    </span>
  );
}
