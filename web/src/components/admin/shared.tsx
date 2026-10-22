"use client";

import { Check, Copy, Lock } from "lucide-react";
import useSWR from "swr";
import type { ReactNode } from "react";
import { useState } from "react";
import { Button, Card, Input, Notice, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import { useToast } from "@/components/toast";
import { initials, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

/** Platform super-admins only, and only after entering the admin password. Everyone else
 * is told plainly they don't belong here. */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { session, loading } = useSession();
  const { data: lock, mutate } = useSWR<{ unlocked: boolean }>(
    session?.user.is_superadmin ? "/api/admin/lock" : null,
    fetcher,
  );
  if (loading || !session || (session.user.is_superadmin && !lock)) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }
  if (!session.user.is_superadmin) {
    return (
      <div className="mx-auto max-w-md py-24 text-center">
        <Lock className="mx-auto h-8 w-8 text-brand-600" />
        <h1 className="mt-3 font-display text-2xl font-bold tracking-tight">YOU DON&apos;T BELONG HERE</h1>
        <p className="mt-1 text-sm text-zinc-500">This area is for the BlackSync team only.</p>
      </div>
    );
  }
  if (!lock?.unlocked) return <AdminUnlock onUnlocked={() => mutate({ unlocked: true })} />;
  return <>{children}</>;
}

function AdminUnlock({ onUnlocked }: { onUnlocked: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/api/admin/unlock", { password });
      onUnlocked();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="flex justify-center py-16">
      <Card className="w-full max-w-sm p-6">
        <form onSubmit={submit} className="space-y-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-900 text-white">
            <Lock className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Admin portal</h1>
            <p className="mt-1 text-sm text-zinc-500">Enter the admin password to continue.</p>
          </div>
          {error && <Notice tone="red">{error}</Notice>}
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Admin password" autoFocus required aria-label="Admin password" />
          <Button variant="primary" className="w-full" loading={busy}>
            Unlock
          </Button>
        </form>
      </Card>
    </div>
  );
}

export function StatTile({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "amber" }) {
  return (
    <Card className="min-w-0 px-4 py-3.5">
      <div className="truncate text-xs font-medium text-zinc-500">{label}</div>
      <div className={cn("mt-1 truncate font-display text-xl font-semibold tabular-nums tracking-tight", tone === "amber" ? "text-amber-700" : "text-zinc-900")}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-zinc-500">{sub}</div>}
    </Card>
  );
}

const AVATAR_TONES = ["bg-orange-100 text-orange-800", "bg-amber-100 text-amber-800", "bg-stone-200 text-stone-700", "bg-rose-100 text-rose-800", "bg-emerald-100 text-emerald-800"];

export function Avatar({ name, className }: { name: string; className?: string }) {
  const tone = AVATAR_TONES[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_TONES.length];
  return <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold", tone, className)}>{initials(name)}</span>;
}

/** A read-only value with a copy button (passwords, invite links). */
export function CopyField({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast("Couldn't copy — select the text and copy it manually", "error");
    }
  };
  return (
    <div className="min-w-0">
      <div className="mb-1.5 text-xs font-medium text-zinc-700">{label}</div>
      <div className="flex min-w-0 items-center gap-2">
        <input
          readOnly
          value={value}
          onFocus={(e) => e.currentTarget.select()}
          className={cn("h-9 min-w-0 flex-1 rounded-lg border border-zinc-200 bg-zinc-50 px-3 text-sm text-zinc-900", mono && "font-mono")}
        />
        <button
          type="button"
          onClick={copy}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-800 hover:bg-zinc-50"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
