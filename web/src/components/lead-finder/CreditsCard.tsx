"use client";

import { Coins, Plus } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, Input } from "@/components/ui";
import { ApiError, post } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { LeadFinderUsage } from "./types";

const PRESETS = [50, 100, 500];

/** Lead-lookup credit balance (separate from calling credits). Platform admins can top up right here. */
export function CreditsCard({ usage, onChanged }: { usage: LeadFinderUsage | undefined; onChanged?: () => void }) {
  const empty = !!usage && !usage.unlimited && usage.credits <= 0;
  const { session } = useSession();
  const isAdmin = !!session?.user.is_superadmin;
  return (
    <Card className="h-fit p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
        <Coins className={cn("h-3.5 w-3.5", empty ? "text-amber-500" : "text-brand-500")} /> Lookup credits
      </div>
      <div className={cn("mt-1 font-display text-2xl font-semibold tabular-nums", empty ? "text-amber-700" : "text-zinc-900")}>
        {!usage ? "—" : usage.unlimited ? "Unlimited" : usage.credits.toLocaleString()}
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
        1 credit per owner found. No match or errors cost nothing. Separate from your calling credits.
      </p>
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
        <Plus className="h-3.5 w-3.5" /> Add credits
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
