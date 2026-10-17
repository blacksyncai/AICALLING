"use client";

import { Check, ChevronDown, Crown, Loader2, Search } from "lucide-react";
import { Fragment, useEffect, useId, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { ModelCatalog, ModelOption } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Input } from "../ui";
import { listKeyHandler, usePopover } from "./picker-utils";

const GROUP_ORDER: ModelOption["group"][] = ["recommended", "fast", "advanced", "other"];
const GROUP_LABELS: Record<ModelOption["group"], string> = { recommended: "Recommended", fast: "Fast", advanced: "Advanced", other: "Other" };
const TRAIT_LABELS: Record<string, string> = {
  general: "general calls",
  booking: "booking",
  transfer: "call transfers",
  complex_scripts: "complex scripts",
};

const SUPER = "BlackSync Super Intelligence";

/** Model name, with "BlackSync Super Intelligence" in purple. */
export function ModelName({ name, className }: { name: string; className?: string }) {
  if (!name.startsWith(SUPER)) return <span className={cn("font-medium text-zinc-900", className)}>{name}</span>;
  return (
    <span className={cn("font-medium text-zinc-900", className)}>
      <span className="bs-super font-semibold">{SUPER}</span>
      {name.slice(SUPER.length)}
    </span>
  );
}

/** Crown for premium models (more than 1 credit per minute). */
function PremiumCrown({ rate }: { rate?: number }) {
  if (rate === undefined || rate <= 1) return null;
  return (
    <span title={`Premium model · ${rate} credits per minute`} aria-label="Premium model" className="inline-flex">
      <Crown className="h-3.5 w-3.5 fill-amber-400 text-amber-500" />
    </span>
  );
}

/** "1.2 cr/min" — what the model costs per minute of talk time. */
function CostPill({ rate, compact }: { rate?: number; compact?: boolean }) {
  if (rate === undefined) return null;
  const premium = rate > 1;
  return (
    <span
      title={`${rate} credits per minute of talk time`}
      className={cn(
        "shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums ring-1",
        premium ? "bg-amber-400/10 text-amber-600 ring-amber-400/40" : "bg-emerald-400/10 text-emerald-600 ring-emerald-400/30",
        compact && "px-1.5 text-[10px]",
      )}
    >
      {rate} cr/min
    </span>
  );
}

const isBlackSync = (m: ModelOption) => m.provider === "BlackSync";

function customModel(id: string): ModelOption {
  return { id, name: "Current model", provider: "", description: "The model this agent uses now.", speed: null, tags: [], recommended_for: [], status: "unknown", group: "other" };
}

/**
 * Compact, searchable, grouped LLM model selector (combobox + listbox).
 *
 * `traits` are this agent's features (e.g. "booking", "transfer"); a model whose catalog
 * `recommended_for` lists one of them gets a "Fits this agent" badge.
 */
export function ModelPicker({
  catalog,
  loading,
  error,
  fallbackIds = [],
  value,
  onChange,
  traits = [],
  inline = false,
}: {
  catalog?: ModelCatalog;
  loading?: boolean;
  error?: boolean;
  /** Plain model ids to offer if the catalog can't be loaded. */
  fallbackIds?: string[];
  value: string;
  onChange: (id: string) => void;
  traits?: string[];
  inline?: boolean;
}) {
  const uid = useId();
  const { open, setOpen, close, rootRef, triggerRef } = usePopover<HTMLButtonElement>({ defaultOpen: inline, dismissOnOutside: !inline });
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(-1);
  const keyboardNavigation = useRef(false);
  // Same per-model credit rates billing uses (admin-editable).
  const { data: rates } = useSWR<{ model_rates: Record<string, number> }>("/api/billing/rates", fetcher, { revalidateOnFocus: false });
  const rateOf = (id: string) => rates?.model_rates[id];

  const models = useMemo(() => {
    const list: ModelOption[] = catalog?.models?.length ? catalog.models : fallbackIds.map(customModel).map((m) => ({ ...m, provider: "", description: "" }));
    return value && !list.some((m) => m.id === value) ? [...list, customModel(value)] : list;
  }, [catalog, fallbackIds, value]);
  const selected = models.find((m) => m.id === value);
  const fits = (m: ModelOption) => traits.some((t) => m.recommended_for.includes(t));
  const groupLabel = (g: ModelOption["group"]) => catalog?.groups.find((x) => x.key === g)?.label ?? GROUP_LABELS[g];

  const needle = q.trim().toLowerCase();
  const filtered = models.filter((m) => !needle || `${m.name} ${m.id} ${m.provider} ${m.description}`.toLowerCase().includes(needle));
  // Flattened in group order so arrow keys walk the visual order.
  const flat = GROUP_ORDER.flatMap((g) => filtered.filter((m) => m.group === g));

  useEffect(() => {
    if (!open) return;
    const i = flat.findIndex((m) => m.id === value);
    setActive(i >= 0 ? i : flat.length ? 0 : -1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, needle]);

  useEffect(() => {
    if (active >= 0 && (!inline || keyboardNavigation.current)) listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
    keyboardNavigation.current = false;
  }, [active, inline]);

  function openPicker() {
    setQ("");
    setOpen(true);
    requestAnimationFrame(() => searchRef.current?.focus());
  }
  function choose(id: string) {
    onChange(id);
    if (!inline) close();
  }
  const onKeyDown = listKeyHandler(flat.length, active, (i) => { keyboardNavigation.current = true; setActive(i); }, (i) => choose(flat[i].id));
  const optionId = (i: number) => `${uid}-m-${i}`;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? close() : openPicker())}
        onKeyDown={(e) => {
          if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !open) {
            e.preventDefault();
            openPicker();
          }
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Model: ${selected?.name ?? value}. Change model`}
        className={cn(
          "flex min-h-11 w-full items-center gap-2 rounded-lg border bg-white px-3 py-2 text-left text-sm transition",
          "focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100",
          open ? "border-brand-500 ring-2 ring-brand-100" : "border-zinc-200 hover:border-zinc-300",
        )}
      >
        <span className="min-w-0 flex-1">
          <span className="inline-flex max-w-full flex-wrap items-center gap-1.5 align-middle">
            <ModelName name={selected?.name ?? value} />
            <PremiumCrown rate={rateOf(value)} />
            <CostPill rate={rateOf(value)} compact />
          </span>
          {selected && rateOf(value) === undefined && (
            <span className="text-zinc-500">
              {" · "}
              {[isBlackSync(selected) ? selected.provider : null, selected.speed === "fast" ? "Fast" : null].filter(Boolean).join(" · ")}
            </span>
          )}
        </span>
        {loading ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-zinc-400" /> : <ChevronDown className={cn("h-4 w-4 shrink-0 text-zinc-400 transition", open && "rotate-180")} />}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Choose a model"
          data-solid
          className={cn("mt-2 flex flex-col rounded-xl border border-zinc-200 bg-white", inline ? "relative w-full" : "absolute right-0 top-full z-50 max-h-[min(30rem,72vh)] w-[max(100%,min(26rem,calc(100vw-2rem)))] shadow-xl")}
        >
          <div className="border-b border-zinc-100 p-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
              <Input
                ref={searchRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Search models…"
                className="pl-9"
                role="combobox"
                aria-expanded
                aria-controls={`${uid}-models`}
                aria-activedescendant={active >= 0 ? optionId(active) : undefined}
                aria-autocomplete="list"
                aria-label="Search models"
              />
            </div>
          </div>
          <div ref={listRef} id={`${uid}-models`} role="listbox" aria-label="Models" className={cn("min-h-0 flex-1 py-1", !inline && "scroll-thin overflow-y-auto")}>
            {flat.length === 0 && <p className="px-4 py-6 text-center text-sm text-zinc-500">No models match “{q.trim()}”.</p>}
            {GROUP_ORDER.map((g) => {
              const rows = flat.filter((m) => m.group === g);
              if (!rows.length) return null;
              return (
                <Fragment key={g}>
                  <div role="group" aria-labelledby={`${uid}-g-${g}`}>
                    <div id={`${uid}-g-${g}`} className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
                      {groupLabel(g)}
                    </div>
                    {rows.map((m) => {
                      const i = flat.indexOf(m);
                      const isSel = m.id === value;
                      return (
                        <div
                          key={m.id}
                          id={optionId(i)}
                          data-index={i}
                          role="option"
                          aria-selected={isSel}
                          onClick={() => choose(m.id)}
                          onMouseMove={() => active !== i && setActive(i)}
                          className={cn(
                            "mx-1.5 flex cursor-pointer items-start gap-2 rounded-lg px-3 py-2.5 transition-colors",
                            isBlackSync(m) && "bs-model-row",
                            i === active && "bg-zinc-50",
                            isSel && "bg-brand-50 ring-1 ring-brand-500/40",
                          )}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex items-start gap-2">
                              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 text-sm">
                                <ModelName name={m.name} />
                                <PremiumCrown rate={rateOf(m.id)} />
                              </div>
                              <CostPill rate={rateOf(m.id)} />
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                              {isBlackSync(m) && <span className="font-medium text-violet-500">{m.provider}</span>}
                              {m.speed && <span className="text-zinc-500">{isBlackSync(m) ? "· " : ""}{m.speed === "fast" ? "Fast" : "Standard speed"}</span>}
                              {m.tags.includes("recommended") && (
                                <span className="rounded bg-brand-50 px-1.5 text-[10px] font-semibold text-brand-700 ring-1 ring-brand-100">Recommended</span>
                              )}
                              {fits(m) && (
                                <span
                                  className="rounded bg-emerald-50 px-1.5 text-[10px] font-semibold text-emerald-700"
                                  title={`Suited to ${m.recommended_for.filter((t) => traits.includes(t)).map((t) => TRAIT_LABELS[t] ?? t).join(", ")}`}
                                >
                                  Fits this agent
                                </span>
                              )}
                            </div>
                            {m.description && (
                              <div className={cn("mt-1 text-xs leading-relaxed", isBlackSync(m) ? "bs-desc font-semibold text-zinc-700" : "text-zinc-500")}>
                                {m.description}
                              </div>
                            )}
                          </div>
                          <Check className={cn("mt-0.5 h-4 w-4 shrink-0 text-brand-600", !isSel && "invisible")} aria-hidden />
                        </div>
                      );
                    })}
                  </div>
                </Fragment>
              );
            })}
          </div>
          {error && <p className="border-t border-zinc-100 px-3 py-2 text-xs text-amber-700">Couldn&apos;t load model details — showing the basic list.</p>}
        </div>
      )}
    </div>
  );
}
