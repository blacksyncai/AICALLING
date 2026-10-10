"use client";

import { Minus, Plus, RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui";
import type { KnowledgeChange } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { shortUrl } from "./api";

/** Suggested updates from a rescan: grouped adds/removes, pick what to apply. */
export function PendingChanges({
  changes,
  sectionTitles,
  onApply,
  onDismiss,
}: {
  changes: KnowledgeChange[];
  sectionTitles: Record<string, string>;
  onApply: (ids: string[]) => Promise<void>;
  onDismiss: (ids: string[]) => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<"selected" | "all" | "dismiss" | null>(null);
  const groups = useMemo(
    () =>
      [
        { action: "add" as const, title: "New information found", items: changes.filter((c) => c.action === "add") },
        { action: "remove" as const, title: "No longer on your website", items: changes.filter((c) => c.action === "remove") },
      ].filter((g) => g.items.length > 0),
    [changes],
  );
  const live = [...selected].filter((id) => changes.some((c) => c.id === id));

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  async function run(kind: "selected" | "all" | "dismiss") {
    setBusy(kind);
    try {
      if (kind === "dismiss") await onDismiss(live);
      else await onApply(kind === "all" ? [] : live);
      setSelected(new Set());
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50/40" aria-labelledby="pending-title">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-amber-100 px-4 py-3">
        <div className="min-w-0">
          <h2 id="pending-title" className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
            <RefreshCcw className="h-4 w-4 text-amber-600" /> Suggested updates
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">{changes.length}</span>
          </h2>
          <p className="mt-0.5 text-xs text-zinc-600">
            Your website changed since the last scan. Nothing is updated until you approve it — and anything you added or edited yourself is never changed
            automatically.
          </p>
        </div>
      </div>
      <div className="space-y-4 px-4 py-3">
        {groups.map((g) => (
          <div key={g.action}>
            <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">{g.title}</h3>
            <ul className="space-y-1.5">
              {g.items.map((c) => (
                <li key={c.id}>
                  <label
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-lg border bg-white px-3 py-2 hover:border-zinc-300",
                      selected.has(c.id) ? "border-brand-200 ring-1 ring-brand-100" : "border-zinc-200",
                    )}
                  >
                    <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} className="mt-0.5 h-4 w-4 shrink-0 accent-brand-600" />
                    <span
                      className={cn(
                        "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded",
                        c.action === "add" ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700",
                      )}
                      aria-label={c.action === "add" ? "Add" : "Remove"}
                    >
                      {c.action === "add" ? <Plus className="h-3 w-3" /> : <Minus className="h-3 w-3" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={cn("block text-sm text-zinc-800", c.action === "remove" && "text-zinc-500 line-through decoration-zinc-300")}>
                        {c.item.text}
                      </span>
                      <span className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-zinc-500">
                        <span>{sectionTitles[c.section] ?? c.section}</span>
                        {c.item.source_url && <span className="truncate">· {shortUrl(c.item.source_url)}</span>}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="flex flex-col-reverse gap-2 border-t border-amber-100 px-4 py-3 sm:flex-row sm:justify-end">
        <Button size="sm" variant="ghost" onClick={() => run("dismiss")} loading={busy === "dismiss"} disabled={!!busy}>
          {live.length ? `Dismiss selected (${live.length})` : "Dismiss all"}
        </Button>
        <Button size="sm" onClick={() => run("selected")} loading={busy === "selected"} disabled={!!busy || live.length === 0}>
          Apply selected{live.length ? ` (${live.length})` : ""}
        </Button>
        <Button size="sm" variant="primary" onClick={() => run("all")} loading={busy === "all"} disabled={!!busy}>
          Apply all
        </Button>
      </div>
    </section>
  );
}
