"use client";

import { Check, ChevronRight, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Button, Input, Textarea } from "@/components/ui";
import { useToast } from "@/components/toast";
import { post } from "@/lib/api";
import { PROMPT_SECTIONS } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { DiffView } from "./DiffView";

type RegenState = { asking: boolean; instruction: string; loading: boolean; proposal: string | null };
const IDLE: RegenState = { asking: false, instruction: "", loading: false, proposal: null };

/** The AI-built script as 12 labelled, collapsible sections, each with "Regenerate". */
export function SectionsEditor({
  agentId,
  sections,
  onChange,
  beforeRegenerate,
}: {
  agentId: string;
  sections: Record<string, string>;
  onChange: (key: string, text: string) => void;
  beforeRegenerate?: () => Promise<boolean>;
}) {
  const toast = useToast();
  const [open, setOpen] = useState<Record<string, boolean>>({ identity: true });
  const [regen, setRegen] = useState<Record<string, RegenState>>({});
  const allOpen = PROMPT_SECTIONS.every(([k]) => open[k]);

  const patchRegen = (key: string, p: Partial<RegenState>) => setRegen((r) => ({ ...r, [key]: { ...(r[key] ?? IDLE), ...p } }));

  async function regenerate(key: string) {
    const st = regen[key] ?? IDLE;
    if (beforeRegenerate && !(await beforeRegenerate())) return;
    patchRegen(key, { loading: true });
    try {
      const res = await post<{ section: string; text: string }>(`/api/agent-builder/agents/${agentId}/regenerate`, {
        section: key,
        instruction: st.instruction.trim() || undefined,
      });
      patchRegen(key, { loading: false, asking: false, proposal: res.text ?? "" });
      setOpen((o) => ({ ...o, [key]: true }));
    } catch (e) {
      patchRegen(key, { loading: false });
      toast((e as Error).message, "error");
    }
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-zinc-700">Script</span>
        <button
          className="text-xs font-medium text-zinc-500 hover:text-zinc-800"
          onClick={() => setOpen(allOpen ? {} : Object.fromEntries(PROMPT_SECTIONS.map(([k]) => [k, true])))}
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <div className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white">
        {PROMPT_SECTIONS.map(([key, label], idx) => {
          const text = sections[key] ?? "";
          const isOpen = !!open[key];
          const st = regen[key] ?? IDLE;
          const panelId = `section-${key}`;
          return (
            <div key={key}>
              <div className="flex items-center gap-2 px-3 py-2">
                <button
                  className="flex min-w-0 flex-1 items-center gap-2 py-1 text-left"
                  onClick={() => setOpen((o) => ({ ...o, [key]: !isOpen }))}
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                >
                  <ChevronRight className={cn("h-4 w-4 shrink-0 text-zinc-400 transition-transform", isOpen && "rotate-90")} />
                  <span className="w-5 shrink-0 text-[11px] tabular-nums text-zinc-400">{idx + 1}</span>
                  <span className="truncate text-sm font-medium text-zinc-900">{label}</span>
                  {!text.trim() && <span className="shrink-0 text-[11px] text-zinc-400">empty</span>}
                  {st.proposal !== null && <span className="shrink-0 rounded bg-brand-50 px-1.5 py-0.5 text-[10px] font-medium text-brand-700">New version</span>}
                </button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 shrink-0 px-2"
                  onClick={() => {
                    patchRegen(key, { asking: !st.asking });
                    setOpen((o) => ({ ...o, [key]: true }));
                  }}
                  loading={st.loading}
                  aria-label={`Regenerate ${label}`}
                >
                  {!st.loading && <RotateCcw className="h-3.5 w-3.5" />}
                  <span className="hidden sm:inline">Regenerate</span>
                </Button>
              </div>
              {isOpen && (
                <div id={panelId} className="space-y-3 px-3 pb-3">
                  {st.asking && (
                    <form
                      className="flex flex-col gap-2 rounded-lg border border-brand-100 bg-brand-50/50 p-2 sm:flex-row"
                      onSubmit={(e) => {
                        e.preventDefault();
                        regenerate(key);
                      }}
                    >
                      <Input
                        autoFocus
                        value={st.instruction}
                        onChange={(e) => patchRegen(key, { instruction: e.target.value })}
                        placeholder="Optional: what should change? e.g. keep it shorter"
                        className="h-8 text-xs"
                        aria-label={`Instruction for regenerating ${label}`}
                      />
                      <div className="flex shrink-0 gap-2">
                        <Button size="sm" variant="primary" type="submit" loading={st.loading}>
                          {!st.loading && <Sparkles className="h-3.5 w-3.5" />} Rewrite
                        </Button>
                        <Button size="sm" variant="ghost" type="button" onClick={() => patchRegen(key, { asking: false })}>
                          Cancel
                        </Button>
                      </div>
                    </form>
                  )}
                  {st.proposal !== null ? (
                    <div className="space-y-2">
                      <div className="text-xs font-medium text-zinc-700">Proposed change</div>
                      <DiffView before={text} after={st.proposal} className="max-h-80 overflow-y-auto" />
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => {
                            onChange(key, st.proposal ?? "");
                            patchRegen(key, { proposal: null, instruction: "" });
                          }}
                        >
                          <Check className="h-3.5 w-3.5" /> Accept
                        </Button>
                        <Button size="sm" onClick={() => patchRegen(key, { proposal: null })}>
                          <X className="h-3.5 w-3.5" /> Discard
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <Textarea
                      value={text}
                      onChange={(e) => onChange(key, e.target.value)}
                      rows={Math.min(18, Math.max(4, text.split("\n").length + 1))}
                      className="text-[13px]"
                      aria-label={label}
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
