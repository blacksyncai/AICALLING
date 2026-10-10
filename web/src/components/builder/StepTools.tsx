"use client";

import { useMemo } from "react";
import type { BuilderCatalog } from "@/lib/builder";
import { Chip } from "./parts";

type Integration = BuilderCatalog["integrations"][number];

/** Compact tools picker for the Fine-tune step: working tools as chips, CRMs listed as coming soon. */
export function ToolsPicker({
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
  const { usable, soon } = useMemo(() => {
    const items = (catalog?.integrations ?? []) as Integration[];
    const relevant = (i: Integration) => (industry && i.industries?.includes(industry) ? 0 : 1);
    const sorted = items.map((i, idx) => ({ i, idx })).sort((a, b) => relevant(a.i) - relevant(b.i) || a.idx - b.idx).map(({ i }) => i);
    return { usable: sorted.filter((i) => i.status !== "coming_soon"), soon: sorted.filter((i) => i.status === "coming_soon") };
  }, [catalog, industry]);

  function toggle(key: string) {
    onChange(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);
  }

  if (!catalog) return <div className="h-8 w-64 animate-pulse rounded-full bg-zinc-100" />;

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Tools you use" className="flex flex-wrap gap-2">
        {usable.map((i) => (
          <Chip key={i.key} selected={selected.includes(i.key)} onClick={() => toggle(i.key)} title={i.detail}>
            {i.label}
            {i.status === "needs_setup" && <span className="ml-1 text-[10px] font-normal text-amber-700">needs setup</span>}
          </Chip>
        ))}
      </div>
      {soon.length > 0 && (
        <p className="text-xs leading-relaxed text-zinc-500">
          <span className="font-medium text-zinc-600">Coming soon:</span> {soon.map((i) => i.label).join(", ")}. Connect them today through Zapier using
          Integrations → Webhooks.
        </p>
      )}
    </div>
  );
}
