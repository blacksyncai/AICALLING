"use client";

import { AlertTriangle, CheckCircle2, ChevronRight, XCircle } from "lucide-react";
import { useState } from "react";
import type { BuilderInfo } from "@/lib/builder";
import { cn } from "@/lib/utils";

/** The generator's quality-gate results for an AI-built agent, collapsed to one line by default. */
export function QualityPanel({ quality }: { quality: NonNullable<BuilderInfo["quality"]> }) {
  const [open, setOpen] = useState(false);
  const passed = quality.checks.filter((c) => c.status === "pass").length;
  const warnings = quality.checks.filter((c) => c.status === "warn").length;
  return (
    <div className="mb-3 rounded-xl border border-zinc-200 bg-white">
      <button className="flex w-full items-center gap-2 px-3 py-2.5 text-left" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <ChevronRight className={cn("h-4 w-4 shrink-0 text-zinc-400 transition-transform", open && "rotate-90")} />
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
        <span className="min-w-0 flex-1 truncate text-sm text-zinc-800">
          Quality checks: {passed} of {quality.checks.length} passed
          {warnings > 0 && <span className="text-amber-700"> · {warnings} to review</span>}
        </span>
        <span className="shrink-0 text-xs tabular-nums text-zinc-400">{quality.words.toLocaleString()} words</span>
      </button>
      {open && (
        <ul className="space-y-2 border-t border-zinc-100 px-3 py-3">
          {quality.checks.map((c) => (
            <li key={c.key} className="flex items-start gap-2 text-xs">
              {c.status === "pass" ? (
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
              ) : c.status === "warn" ? (
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
              ) : (
                <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" />
              )}
              <span className="min-w-0">
                <span className="font-medium text-zinc-800">{c.label}</span> <span className="text-zinc-500">— {c.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
