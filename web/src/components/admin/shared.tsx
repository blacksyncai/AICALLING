"use client";

import { Check, Copy, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { Card, Notice, Spinner } from "@/components/ui";
import { useToast } from "@/components/toast";
import { initials, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

/** Renders children only for platform super-admins. */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { session, loading } = useSession();
  if (loading || !session) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }
  if (!session.user.is_superadmin) {
    return (
      <div className="mx-auto max-w-md py-10">
        <Notice tone="red">
          <span className="flex items-center gap-2 font-medium">
            <ShieldAlert className="h-4 w-4" /> Admins only
          </span>
          <span className="mt-1 block">The admin portal is only available to BlackSync platform administrators.</span>
        </Notice>
      </div>
    );
  }
  return <>{children}</>;
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

export const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString();
