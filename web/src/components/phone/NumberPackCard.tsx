"use client";

import { Check, Minus, Plus, RefreshCw, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Modal } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { PhoneNumberItem } from "@/lib/types";

interface Packs {
  name: string;
  amount_cents: number;
  per_pack: number;
  refresh_days: number;
  available: boolean;
  subscribed: boolean;
  helcim: boolean;
  packs: number;
  numbers: PhoneNumberItem[];
  next_refresh_at: string | null;
  credits: { total: number; used: number; open: number };
}

const usd = (c: number) => `$${(c / 100).toFixed(0)}`;
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");

/** Fresh Number Pack: 10 number credits per pack. The customer picks each number; every one is swapped for a
    fresh number in the same area code each month. `pickHref` is where the number search is. */
export function NumberPackCard({ onChanged, pickHref = "#get-number" }: { onChanged: () => void; pickHref?: string }) {
  const toast = useToast();
  const { data, mutate } = useSWR<Packs>("/api/billing/addons/phone-packs", fetcher);
  const [confirm, setConfirm] = useState<number | null>(null); // the pack count being confirmed
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const per = data.per_pack;
  const owned = data.packs;

  async function apply(quantity: number) {
    setBusy(true);
    try {
      const out = await post<Packs>("/api/billing/addons/phone-packs", { quantity, confirm: true });
      await mutate(out, false);
      onChanged();
      setConfirm(null);
      toast(quantity > owned ? `${(quantity - owned) * per} number credits added — pick your numbers` : "Number pack removed");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const adding = confirm != null && confirm > owned;
  return (
    <section className="relative overflow-hidden rounded-2xl bg-white shadow-xs ring-1 ring-zinc-900/5">
      <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 h-44 w-44 rounded-full bg-brand-500/10 blur-2xl" />
      <div className="relative space-y-4 p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-display text-lg font-semibold tracking-tight text-zinc-900">{data.name}</h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/15">
                <ShieldCheck className="h-3 w-3" /> Anti-spam
              </span>
            </div>
            <p className="mt-1 text-sm text-zinc-600">{data.per_pack} number credits: pick the local numbers you want, and each one is swapped for a fresh one every month. Stop worrying about spam labels.</p>
          </div>
          <div className="shrink-0 text-right">
            <div className="font-display text-2xl font-semibold tabular-nums text-zinc-900">{usd(data.amount_cents)}</div>
            <div className="text-xs text-zinc-500">per month</div>
          </div>
        </div>

        <ul className="space-y-1.5 text-sm text-zinc-700">
          {[
            `Spread your call volume across ${data.per_pack} numbers so no single one gets overused`,
            `Every number is replaced with a new one every ${data.refresh_days} days, before carriers flag it`,
            "Campaigns keep rotating on their own: new numbers slot in where the old ones were",
          ].map((t) => (
            <li key={t} className="flex gap-2">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
              {t}
            </li>
          ))}
        </ul>

        {owned > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-zinc-50 px-3 py-2.5 text-sm text-zinc-700 ring-1 ring-zinc-900/5">
            <span className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4 shrink-0 text-brand-600" />
              <span>
                <strong>{data.credits.open}</strong> of {data.credits.total} credits left · {data.credits.used} number{data.credits.used === 1 ? "" : "s"} picked
                {data.next_refresh_at && <> · next fresh number {day(data.next_refresh_at)}</>}
              </span>
            </span>
            {data.credits.open > 0 && (
              <Link href={pickHref} className="inline-flex items-center gap-1 rounded-full bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-700">
                <Search className="h-3.5 w-3.5" /> Pick your numbers
              </Link>
            )}
          </div>
        )}

        {!data.subscribed ? (
          <p className="text-sm text-zinc-600">
            Added to a BlackSync plan.{" "}
            <Link href="/billing?tab=plans" className="font-medium text-brand-700 hover:underline">
              Choose a plan →
            </Link>
          </p>
        ) : data.helcim ? (
          <p className="text-sm text-zinc-600">Contact support and we&apos;ll add a pack to your account.</p>
        ) : !data.available ? (
          <p className="text-sm text-zinc-500">Coming soon.</p>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <Button variant="primary" className="rounded-full!" onClick={() => setConfirm(owned + 1)} disabled={busy || owned >= 10}>
              <Plus className="h-4 w-4" /> {owned ? "Add another pack" : `Get ${data.per_pack} number credits`}
            </Button>
            {owned > 0 && (
              <Button className="rounded-full!" onClick={() => setConfirm(owned - 1)} disabled={busy}>
                <Minus className="h-4 w-4" /> Remove a pack
              </Button>
            )}
          </div>
        )}
      </div>

      <Modal open={confirm != null} onClose={() => !busy && setConfirm(null)} title={adding ? "Add a Fresh Number Pack?" : "Remove a Fresh Number Pack?"}>
        <div className="space-y-4 text-sm">
          <dl className="divide-y divide-zinc-100 rounded-xl border border-zinc-200">
            <div className="flex justify-between px-4 py-2.5">
              <dt className="text-zinc-500">Packs</dt>
              <dd className="font-medium">
                {owned} → {confirm}
              </dd>
            </div>
            <div className="flex justify-between px-4 py-2.5">
              <dt className="text-zinc-500">Monthly change</dt>
              <dd className="font-medium">
                {adding ? "+" : "−"}
                {usd(data.amount_cents)} / month
              </dd>
            </div>
            <div className="px-4 py-2.5 text-zinc-600">
              {adding
                ? `You get ${per} number credits right away: pick the exact numbers you want with "Get a local number". The prorated amount for the rest of this billing period is charged now, then ${usd(data.amount_cents)} with your plan each month.`
                : `The ${per} newest pack numbers are released and taken out of your campaigns. Unused time is credited to your next invoice.`}
            </div>
          </dl>
          <div className="flex justify-end gap-2">
            <Button className="rounded-full!" onClick={() => setConfirm(null)} disabled={busy}>
              Cancel
            </Button>
            <Button className="rounded-full!" variant="primary" loading={busy} onClick={() => confirm != null && void apply(confirm)}>
              {adding ? `Pay and get ${per} credits` : "Remove pack"}
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
