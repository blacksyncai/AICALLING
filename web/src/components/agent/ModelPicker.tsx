"use client";

import { Check, ChevronDown, Loader2, Search } from "lucide-react";
import { Fragment, useEffect, useId, useMemo, useRef, useState } from "react";
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

function customModel(id: string): ModelOption {
  return { id, name: id, provider: "Custom", description: "Saved on this agent; not in the model catalog.", speed: null, tags: [], recommended_for: [], status: "unknown", group: "other" };
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
}: {
  catalog?: ModelCatalog;
  loading?: boolean;
  error?: boolean;
  /** Plain model ids to offer if the catalog can't be loaded. */
  fallbackIds?: string[];
  value: string;
  onChange: (id: string) => void;
  traits?: string[];
}) {
  const uid = useId();
  const { open, setOpen, close, rootRef, triggerRef } = usePopover<HTMLButtonElement>();
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(-1);

  const models = useMemo(() => {
    const list: ModelOption[] = catalog?.models?.length ? catalog.models : fallbackIds.map(customModel).map((m) => ({ ...m, provider: "OpenAI", description: "" }));
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
    if (active >= 0) listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  function openPicker() {
    setQ("");
    setOpen(true);
    requestAnimationFrame(() => searchRef.current?.focus());
  }
  function choose(id: string) {
    onChange(id);
    close();
  }
  const onKeyDown = listKeyHandler(flat.length, active, setActive, (i) => choose(flat[i].id));
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
          "flex h-9 w-full items-center gap-2 rounded-lg border bg-white px-3 text-left text-sm transition",
          "focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100",
          open ? "border-brand-500 ring-2 ring-brand-100" : "border-zinc-200 hover:border-zinc-300",
        )}
      >
        <span className="min-w-0 flex-1 truncate">
          <span className="font-medium text-zinc-900">{selected?.name ?? value}</span>
          {selected && (
            <span className="text-zinc-500">
              {" · "}
              {[selected.provider, selected.speed === "fast" ? "Fast" : null].filter(Boolean).join(" · ")}
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
          className="absolute inset-x-0 top-full z-50 mt-2 flex max-h-[min(26rem,70vh)] min-w-[min(20rem,calc(100vw-2rem))] flex-col rounded-xl border border-zinc-200 bg-white shadow-xl"
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
          <div ref={listRef} id={`${uid}-models`} role="listbox" aria-label="Models" className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1">
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
                          className={cn("flex cursor-pointer items-start gap-2 px-3 py-2", i === active && "bg-zinc-50", isSel && "bg-brand-50")}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5 text-sm">
                              <span className="font-medium text-zinc-900">{m.name}</span>
                              <span className="text-xs text-zinc-400">{m.provider}</span>
                              {m.speed && <span className="text-xs text-zinc-500">· {m.speed === "fast" ? "Fast" : "Standard speed"}</span>}
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
                            {m.description && <div className="text-xs text-zinc-500">{m.description}</div>}
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
