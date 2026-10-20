"use client";

import { Gift, UserSearch } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Notice, Spinner } from "@/components/ui";
import { Card, CardHeader, emptyCls, listCls, rowCls } from "./surface";
import { PillBadge, PricingButton, PricingCard, PricingHeading } from "@/components/ui/pricing";
import { fetcher, post } from "@/lib/api";
import { CountryPopup } from "./CountryPopup";
import { cn } from "@/lib/utils";
import { type Catalog, type LookupStatus, fmtDateTime, usd } from "./types";

interface LookupsData extends LookupStatus {
  ledger: { id: string; amount_cents: number; balance_after_cents: number; kind: string; note: string; created_at: string | null }[];
}

export function LookupsTab({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data } = useSWR<LookupsData>("/api/billing/lookups", fetcher);
  const { data: cat } = useSWR<Catalog>("/api/billing/catalog", fetcher);
  const [busy, setBusy] = useState<string | null>(null);
  const { data: countryData } = useSWR<{ country: string }>("/api/billing/country", fetcher);
  const [askCountry, setAskCountry] = useState<string | null>(null);

  if (!data || !cat)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  async function add(key: string) {
    if (!countryData?.country) {
      setAskCountry(key);
      return;
    }
    setBusy(key);
    try {
      window.location.href = (await post<{ url: string }>("/api/billing/lookups/checkout", { amount: key })).url;
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(null);
    }
  }

  const price = data.price_cents;
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="rounded-2xl p-6 md:col-span-2">
          <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
            <UserSearch className="h-4 w-4" /> Lead lookup balance
          </div>
          <div className="mt-2 font-display text-3xl font-semibold tabular-nums">{data.unlimited ? "Unlimited" : usd(data.balance_cents)}</div>
          <p className="mt-1 text-sm text-zinc-600">
            {price == null
              ? "Paid lookups aren't available yet — you can use your free daily lookups."
              : `${usd(price)} per lookup, ${data.policy === "match" ? "charged only when an owner is found" : "charged for every completed lookup"}. You always confirm the price before a paid lookup runs.`}
          </p>
          <p className="mt-2 text-xs text-zinc-500">This balance can only be used for lead data. It&apos;s separate from calling credits and isn&apos;t refundable as cash.</p>
          {data.prepaid_credits > 0 && <p className="mt-2 text-xs text-zinc-600">You also have {data.prepaid_credits.toLocaleString()} prepaid lookups — they&apos;re used before your balance.</p>}
        </Card>
        <Card className="rounded-2xl p-6">
          <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
            <Gift className="h-4 w-4" /> Free lookups today
          </div>
          <div className="mt-2 font-display text-3xl font-semibold tabular-nums">
            {data.free_remaining}
            <span className="text-lg text-zinc-400"> / {data.free_daily}</span>
          </div>
          <p className="mt-1 text-xs text-zinc-500">Single-address lookups. Resets at midnight UTC. Re-opening a saved result is always free.</p>
          <Link href="/lead-finder" className="mt-3 inline-block text-sm font-medium text-brand-700 hover:text-brand-800">
            Open Lead Finder →
          </Link>
        </Card>
      </div>

      <div>
        <PricingHeading
          title="Lead lookups"
          description="Find owner phone numbers for property addresses. Bigger packs cost less per record, and you're never charged for a lookup that finds no one."
        />
        <div className="grid gap-4 sm:grid-cols-3">
          {cat.lookup_funds.map((f, i) => {
            const records = f.records ?? (price ? Math.floor(f.amount_cents / price) : null);
            const featured = i === 1;
            return (
              <PricingCard
                key={f.key}
                index={i}
                name={["Starter", "Standard", "Bulk"][i] ?? "Top-up"}
                description={
                  records != null
                    ? `${records.toLocaleString()} records${f.per_record_cents ? ` · ${f.per_record_cents}¢ per record` : ""}`
                    : "Added to your lookup balance"
                }
                cents={f.amount_cents}
                features={[
                  "Single addresses: owner numbers in seconds, saved to Contacts in one click",
                  "Bulk: drop in a CSV of addresses, get phone numbers back",
                  "Do Not Call flags on every number",
                  "No charge when no owner is found",
                ]}
                highlighted={featured}
                badge={featured ? <PillBadge>Popular</PillBadge> : null}
                footer={
                  <PricingButton tone={featured ? "brand" : "dark"} loading={busy === f.key} disabled={!canManage || !f.available || !!busy} onClick={() => void add(f.key)}>
                    Add {usd(f.amount_cents, 0)}
                  </PricingButton>
                }
              />
            );
          })}
        </div>
        {!cat.lookup_funds.some((f) => f.available) && (
          <div className="mt-3 ">
            <Notice>Adding funds online isn&apos;t available yet. Contact us to top up your lookup balance.</Notice>
          </div>
        )}
      </div>

      <Card>
        <CardHeader title="Lookup balance history" />
        {data.ledger.length === 0 ? (
          <p className={emptyCls}>No activity yet.</p>
        ) : (
          <ul className={listCls}>
            {data.ledger.map((t) => (
              <li key={t.id} className={cn("flex items-center justify-between gap-3", rowCls)}>
                <span className="min-w-0">
                  <span className="block truncate text-zinc-800">{t.note || t.kind}</span>
                  <span className="text-xs text-zinc-400">{fmtDateTime(t.created_at)}</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className={cn("block font-mono tabular-nums", t.amount_cents > 0 ? "text-emerald-700" : "text-zinc-700")}>
                    {t.amount_cents > 0 ? "+" : ""}
                    {usd(t.amount_cents)}
                  </span>
                  <span className="text-xs tabular-nums text-zinc-400">{usd(t.balance_after_cents)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    <CountryPopup
      open={askCountry !== null}
      onDone={() => { const key = askCountry; setAskCountry(null); if (key) void add(key); }}
      onCancel={() => setAskCountry(null)}
    />
    </div>
  );
}
