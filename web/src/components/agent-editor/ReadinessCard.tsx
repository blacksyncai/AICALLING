"use client";

import { AlertTriangle, CheckCircle2, ChevronDown, OctagonAlert, RefreshCw, Rocket } from "lucide-react";
import Link from "next/link";
import { forwardRef, useEffect, useState } from "react";
import type { ReadinessCheck } from "@/lib/builder";
import { cn } from "@/lib/utils";

export type Readiness = { ready: boolean; checks: ReadinessCheck[] };

const ORDER = { blocker: 0, warning: 1, ok: 2 } as const;

export function CheckIcon({ status, className }: { status: ReadinessCheck["status"]; className?: string }) {
  if (status === "ok") return <CheckCircle2 aria-label="OK" className={cn("h-4 w-4 shrink-0 text-emerald-600", className)} />;
  if (status === "warning") return <AlertTriangle aria-label="Warning" className={cn("h-4 w-4 shrink-0 text-amber-500", className)} />;
  return <OctagonAlert aria-label="Must fix" className={cn("h-4 w-4 shrink-0 text-red-600", className)} />;
}

/** "Fix" link — in-page anchors (#prompt, #voice …) switch editor tabs, everything else navigates. */
export function FixLink({ href, onSection }: { href: string; onSection?: (hash: string) => void }) {
  const cls = "shrink-0 rounded-md px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50";
  if (href.startsWith("#"))
    return (
      <button className={cls} onClick={() => onSection?.(href.slice(1))}>
        Fix
      </button>
    );
  if (href.startsWith("/"))
    return (
      <Link className={cls} href={href}>
        Fix
      </Link>
    );
  return (
    <a className={cls} href={href} target="_blank" rel="noreferrer">
      Fix
    </a>
  );
}

export function CheckList({ checks, onSection }: { checks: ReadinessCheck[]; onSection?: (hash: string) => void }) {
  return (
    <ul className="divide-y divide-zinc-100">
      {checks.map((c) => (
        <li key={c.key} className="flex items-start gap-3 py-2.5">
          <CheckIcon status={c.status} className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-zinc-900">{c.label}</div>
            {c.detail && <div className="mt-0.5 text-xs text-zinc-500">{c.detail}</div>}
          </div>
          {c.status !== "ok" && c.fix_href && <FixLink href={c.fix_href} onSection={onSection} />}
        </li>
      ))}
    </ul>
  );
}

export const ReadinessCard = forwardRef<
  HTMLDivElement,
  { data: Readiness | undefined; error?: Error; loading: boolean; onRefresh: () => void; onSection?: (hash: string) => void; forceOpen?: number }
>(function ReadinessCard({ data, error, loading, onRefresh, onSection, forceOpen }, ref) {
  const checks = [...(data?.checks ?? [])].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  const blockers = checks.filter((c) => c.status === "blocker").length;
  const warnings = checks.filter((c) => c.status === "warning").length;
  const toFix = blockers + warnings;
  const [open, setOpen] = useState<boolean | null>(null);
  const expanded = open ?? toFix > 0;

  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);

  const headline = !data
    ? error
      ? "Couldn't check launch readiness"
      : "Checking launch readiness…"
    : blockers === 0
      ? "Ready to launch"
      : `${blockers} thing${blockers === 1 ? "" : "s"} to fix before launch`;

  return (
    <div ref={ref} tabIndex={-1} className="scroll-mt-32 rounded-xl border border-zinc-200 bg-white shadow-xs focus:outline-none">
      <div className="flex items-center gap-3 px-4 py-3">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            !data ? "bg-zinc-100 text-zinc-400" : blockers ? "bg-red-50 text-red-600" : warnings ? "bg-amber-50 text-amber-600" : "bg-emerald-50 text-emerald-600",
          )}
        >
          {data && blockers ? <OctagonAlert className="h-4 w-4" /> : <Rocket className="h-4 w-4" />}
        </div>
        <button
          className="min-w-0 flex-1 text-left"
          onClick={() => setOpen(!expanded)}
          aria-expanded={expanded}
          aria-controls="readiness-checks"
          disabled={!data}
        >
          <div className="text-sm font-semibold text-zinc-900">{headline}</div>
          <div className="text-xs text-zinc-500">
            {error && !data
              ? error.message
              : data
                ? blockers === 0 && warnings === 0
                  ? "Everything checks out."
                  : [blockers && `${blockers} must fix`, warnings && `${warnings} suggestion${warnings === 1 ? "" : "s"}`].filter(Boolean).join(" · ")
                : "Looking at your script, voice, phone line and credits"}
          </div>
        </button>
        <button onClick={onRefresh} className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" aria-label="Re-check readiness">
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </button>
        {data && checks.length > 0 && (
          <button
            onClick={() => setOpen(!expanded)}
            className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
            aria-label={expanded ? "Hide checks" : "Show checks"}
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} />
          </button>
        )}
      </div>
      {expanded && data && checks.length > 0 && (
        <div id="readiness-checks" className="border-t border-zinc-100 px-4">
          <CheckList checks={checks} onSection={onSection} />
        </div>
      )}
    </div>
  );
});
