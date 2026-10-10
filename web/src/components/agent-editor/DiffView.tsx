"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { diffLines, type DiffLine } from "./diff";

type Row = DiffLine | { type: "gap"; count: number };

const CONTEXT = 2;

/** Readable line diff: added lines green, removed red, long unchanged stretches collapsed. */
export function DiffView({ before, after, className }: { before: string; after: string; className?: string }) {
  const rows = useMemo<Row[]>(() => {
    const lines = diffLines(before, after);
    const keep = lines.map(() => false);
    lines.forEach((l, i) => {
      if (l.type === "same") return;
      for (let k = Math.max(0, i - CONTEXT); k <= Math.min(lines.length - 1, i + CONTEXT); k++) keep[k] = true;
    });
    const out: Row[] = [];
    let gap = 0;
    lines.forEach((l, i) => {
      if (keep[i]) {
        if (gap) out.push({ type: "gap", count: gap });
        gap = 0;
        out.push(l);
      } else gap++;
    });
    if (gap) out.push({ type: "gap", count: gap });
    return out;
  }, [before, after]);

  if (before === after) return <p className="text-xs text-zinc-500">No changes.</p>;

  return (
    <div className={cn("overflow-hidden rounded-lg border border-zinc-200 font-mono text-[12px] leading-relaxed", className)}>
      {rows.map((r, i) =>
        r.type === "gap" ? (
          <div key={i} className="bg-zinc-50 px-3 py-0.5 text-[11px] text-zinc-400">
            ⋯ {r.count} unchanged line{r.count === 1 ? "" : "s"}
          </div>
        ) : (
          <div
            key={i}
            className={cn(
              "flex gap-2 whitespace-pre-wrap break-words px-3",
              r.type === "add" && "bg-emerald-50 text-emerald-900",
              r.type === "remove" && "bg-red-50 text-red-800 line-through decoration-red-300",
              r.type === "same" && "text-zinc-600",
            )}
          >
            <span aria-hidden className="w-3 shrink-0 select-none text-zinc-400">
              {r.type === "add" ? "+" : r.type === "remove" ? "−" : " "}
            </span>
            <span className="min-w-0 flex-1">
              <span className="sr-only">{r.type === "add" ? "Added: " : r.type === "remove" ? "Removed: " : ""}</span>
              {r.text || " "}
            </span>
          </div>
        ),
      )}
    </div>
  );
}
