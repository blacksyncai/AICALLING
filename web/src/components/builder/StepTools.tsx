"use client";

import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge, Input } from "@/components/ui";
import type { BuilderCatalog } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { StepTitle } from "./parts";

type Integration = BuilderCatalog["integrations"][number] & { industries?: string[] };

const STATUS_RANK = { available: 0, needs_setup: 1, coming_soon: 2 } as const;

export function StepTools({
  selected,
  onChange,
  catalog,
  industry,
}: {
  selected: string[];
  onChange: (next: string[]) => void;
  catalog: BuilderCatalog | undefined;
  industry: string | undefined;
}) {
  const [q, setQ] = useState("");

  const list = useMemo(() => {
    const items = (catalog?.integrations ?? []) as Integration[];
    const relevant = (i: Integration) => (industry && i.industries?.includes(industry) ? 0 : 1);
    const needle = q.trim().toLowerCase();
    return items
      .filter((i) => !needle || `${i.label} ${i.category} ${i.detail}`.toLowerCase().includes(needle))
      .map((i, idx) => ({ i, idx }))
      .sort((a, b) => STATUS_RANK[a.i.status] - STATUS_RANK[b.i.status] || relevant(a.i) - relevant(b.i) || a.idx - b.idx)
      .map(({ i }) => i);
  }, [catalog, industry, q]);

  function toggle(key: string) {
    onChange(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);
  }

  return (
    <div>
      <StepTitle title="Which tools does your business use?" description="Pick what you use today. Nothing here is required — you can skip this step." />

      <div className="relative mb-3">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <Input aria-label="Search tools" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search tools" className="pl-9" />
      </div>

      {!catalog ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-xl bg-zinc-100" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <p className="py-8 text-center text-sm text-zinc-500">No tools match &quot;{q}&quot;.</p>
      ) : (
        <ul className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white">
          {list.map((i) => {
            const soon = i.status === "coming_soon";
            const on = selected.includes(i.key);
            const relevant = !!industry && !!i.industries?.includes(industry);
            return (
              <li key={i.key}>
                {soon ? (
                  <div className="flex items-start gap-3 px-4 py-3">
                    <span className="mt-0.5 h-4 w-4 shrink-0 rounded border border-dashed border-zinc-300" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-zinc-500">
                        {i.label}
                        <Badge tone="gray">Coming soon</Badge>
                        {relevant && <span className="text-[11px] font-normal text-zinc-400">Popular in your industry</span>}
                      </span>
                      {i.detail && <span className="mt-0.5 block text-xs leading-relaxed text-zinc-400">{i.detail}</span>}
                    </span>
                  </div>
                ) : (
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    onClick={() => toggle(i.key)}
                    className={cn(
                      "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-500",
                      on ? "bg-brand-50/50" : "hover:bg-zinc-50",
                    )}
                  >
                    <span
                      className={cn(
                        "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border text-white",
                        on ? "border-brand-600 bg-brand-600" : "border-zinc-300 bg-white",
                      )}
                      aria-hidden
                    >
                      {on && (
                        <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2.5}>
                          <path d="M2.5 6.5l2.2 2.2L9.5 3.5" />
                        </svg>
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-zinc-900">
                        {i.label}
                        {i.status === "available" ? <Badge tone="green">Works today</Badge> : <Badge tone="amber">Needs setup</Badge>}
                        {relevant && <span className="text-[11px] font-normal text-zinc-500">Popular in your industry</span>}
                      </span>
                      {i.detail && <span className="mt-0.5 block text-xs leading-relaxed text-zinc-500">{i.detail}</span>}
                    </span>
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
