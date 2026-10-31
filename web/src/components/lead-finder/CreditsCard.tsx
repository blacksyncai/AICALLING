"use client";

import { Coins, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, Input } from "@/components/ui";
import { ApiError, post } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { LeadFinderUsage } from "./types";

const PRESETS = [50, 100, 500];

/** What the account can look up with: free daily lookups, prepaid lookup credits and the lookup balance. */
export function CreditsCard({ usage, onChanged }: { usage: LeadFinderUsage | undefined; onChanged?: () => void }) {
  const { session } = useSession();
  const isAdmin = !!session?.user.is_superadmin;
  const money = (c: number) => `$${(c / 100).toFixed(2)}`;
  const out = !!usage && !usage.unlimited && usage.free_remaining <= 0 && usage.credits <= 0 &&
    (usage.price_cents == null || usage.balance_cents < usage.price_cents);
  return (
    <Card className="h-fit p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
        <Coins className={cn("h-3.5 w-3.5", out ? "text-amber-500" : "text-brand-500")} /> Free lookups today
      </div>
      <div className={cn("mt-1 font-display text-2xl font-semibold tabular-nums", out ? "text-amber-700" : "text-zinc-900")}>
        {!usage ? "—" : usage.unlimited ? "Unlimited" : `${usage.free_remaining} / ${usage.free_daily}`}
      </div>
      {usage && !usage.unlimited && (
        <dl className="mt-3 space-y-1.5 text-xs">
          {usage.credits > 0 && (
            <div className="flex justify-between">
              <dt className="text-zinc-500">Prepaid lookups</dt>
              <dd className="tabular-nums text-zinc-800">{usage.credits.toLocaleString()}</dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-zinc-500">Lookup balance</dt>
            <dd className="tabular-nums text-zinc-800">{money(usage.balance_cents)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-zinc-500">Paid lookup price</dt>
            <dd className="tabular-nums text-zinc-800">{usage.price_cents == null ? "Not available" : money(usage.price_cents)}</dd>
          </div>
        </dl>
      )}
      <p className="mt-2 text-xs leading-relaxed text-zinc-500">
        {usage?.policy === "completed" ? "Paid lookups are charged when they complete." : "Paid lookups are charged only when an owner is found."} Separate from calling credits.
      </p>
      {usage && !usage.unlimited && (
        <Link href="/billing?tab=lookups" className="mt-2 inline-block text-xs font-medium text-brand-700 hover:text-brand-800">
          Add lookup searches →
        </Link>
      )}
      {isAdmin && session?.org && !usage?.unlimited && <AddCredits orgId={session.org.id} onAdded={onChanged} />}
    </Card>
  );
}

/** Admin-only top-up for the account you're working in. Unlocks the admin portal inline if needed. */
export function AddCredits({ orgId, onAdded, compact }: { orgId: string; onAdded?: () => void; compact?: boolean }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("100");
  const [password, setPassword] = useState("");
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);

  async function add() {
    const n = Number(amount);
    if (!Number.isInteger(n) || n <= 0) return toast("Enter a whole number of credits.", "error");
    setBusy(true);
    try {
      if (locked) {
        await post("/api/admin/unlock", { password });
        setLocked(false);
        setPassword("");
      }
      const r = await post<{ credits: number }>(`/api/admin/orgs/${orgId}/lead-credits`, { amount: n, note: "Added from Lead Finder" });
      toast(`Added ${n.toLocaleString()} credits — balance ${r.credits.toLocaleString()}`);
      setOpen(false);
      onAdded?.();
    } catch (e) {
      if (e instanceof ApiError && e.status === 423) {
        setLocked(true);
        toast("Enter the admin password to add credits.", "error");
      } else {
        toast((e as Error).message, "error");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button size="sm" variant={compact ? "primary" : "secondary"} className={cn(!compact && "mt-3 w-full")} onClick={() => setOpen(true)}>
        <Plus className="h-3.5 w-3.5" /> Add prepaid lookups
      </Button>
    );
  }
  return (
    <form
      className="mt-3 space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        void add();
      }}
    >
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setAmount(String(p))}
            className={cn(
              "rounded-md border px-2 py-1 text-xs font-medium tabular-nums",
              amount === String(p) ? "border-brand-500 bg-brand-50 text-brand-700" : "border-zinc-200 text-zinc-600 hover:bg-zinc-50",
            )}
          >
            +{p}
          </button>
        ))}
      </div>
      <Input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="numeric" aria-label="Credits to add" className="h-8 text-sm" />
      {locked && (
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Admin password" aria-label="Admin password" className="h-8 text-sm" autoFocus />
      )}
      <div className="flex gap-2">
        <Button size="sm" variant="primary" type="submit" loading={busy} className="flex-1">
          Add
        </Button>
        <Button size="sm" variant="ghost" type="button" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
