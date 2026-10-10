"use client";

import { Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { SCAN_STEPS } from "./api";

/** The 4-stage "analyzing your website" progress. */
export function ScanProgress({ step, label, website }: { step: number | null; label: string | null; website?: string }) {
  const current = Math.max(0, Math.min(SCAN_STEPS.length - 1, step ?? 0));
  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-4" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
        <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
        {label ?? SCAN_STEPS[current]}…
      </div>
      {website && <p className="mt-0.5 truncate text-xs text-zinc-500">Reading {website}. This usually takes under a minute — you can leave this page.</p>}
      <ol className="mt-3 grid gap-2 sm:grid-cols-4">
        {SCAN_STEPS.map((s, i) => (
          <li key={s} className="flex items-start gap-2 text-xs">
            <span
              className={cn(
                "mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold",
                i < current && "bg-emerald-500 text-white",
                i === current && "bg-blue-600 text-white",
                i > current && "bg-zinc-200 text-zinc-500",
              )}
            >
              {i < current ? <Check className="h-3 w-3" /> : i + 1}
            </span>
            <span className={cn(i === current ? "font-medium text-zinc-900" : i < current ? "text-zinc-600" : "text-zinc-400")}>{s}</span>
          </li>
        ))}
      </ol>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-blue-100">
        <div className="h-full rounded-full bg-blue-600 transition-all duration-500" style={{ width: `${((current + 0.5) / SCAN_STEPS.length) * 100}%` }} />
      </div>
    </div>
  );
}
