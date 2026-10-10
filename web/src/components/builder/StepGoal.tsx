"use client";

import { ChevronDown, PenLine } from "lucide-react";
import { useId, useState } from "react";
import {  } from "@/components/ui";
import { CUSTOM_USE_CASE, type AssistResponse, type BuilderCatalog, type DraftGoal } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { AssistPanel } from "./AssistPanel";
import { customDescription, goalReady, presetKeys, selectedKeys, useCasesFor, withKeys, type GoalUpdater } from "./goal";
import { Chip, Segmented, StepTitle } from "./parts";
import { VoiceInput, VoiceTextarea } from "@/components/MicButton";

type Direction = NonNullable<DraftGoal["direction"]>;

const CUSTOM_PLACEHOLDER =
  "Build an outbound agent that calls homeowners who previously requested a property valuation, checks if they're considering selling, and transfers interested homeowners to my team.";
const EXTRA_PLACEHOLDER =
  "I want the agent to be casual, avoid sounding like a typical salesperson, and ask homeowners if they're open to discussing additional exposure for their listing.";

export function StepGoal({
  goal,
  setGoal,
  catalog,
  industry,
  showErrors,
  runAssist,
}: {
  goal: DraftGoal;
  setGoal: GoalUpdater;
  catalog: BuilderCatalog | undefined;
  industry: string | undefined;
  showErrors: boolean;
  runAssist: (goal: DraftGoal) => Promise<AssistResponse>;
}) {
  const ids = useId();
  const all = useCasesFor(catalog, industry);
  const direction: Direction = goal.direction ?? "outbound";
  const presets = all.filter((u) => u.key !== CUSTOM_USE_CASE && (direction === "both" || u.direction === direction));
  const keys = selectedKeys(goal);
  const chosen = presetKeys(goal);
  const customOn = keys.includes(CUSTOM_USE_CASE);
  const showCustom = customOn || chosen.length === 0;
  const description = customDescription(goal);
  const c = goal.custom ?? {};
  const hasDetails = !!(c.audience || c.tone || c.outcome);
  const [detailsOpen, setDetailsOpen] = useState(hasDetails);
  const labelOf = (k: string) => all.find((u) => u.key === k)?.label ?? k;

  function setDirection(d: Direction) {
    setGoal((g) => {
      const keep = selectedKeys(g).filter((k) => {
        if (k === CUSTOM_USE_CASE || d === "both") return true;
        return all.find((u) => u.key === k)?.direction === d;
      });
      return withKeys({ ...g, direction: d }, keep);
    });
  }

  function toggle(key: string) {
    setGoal((g) => {
      const cur = selectedKeys(g);
      return withKeys(g, cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]);
    });
  }

  function setCustom(patch: Partial<NonNullable<DraftGoal["custom"]>>) {
    setGoal((g) => {
      const next: DraftGoal = { ...g, custom: { description: customDescription(g), ...g.custom, ...patch } };
      // Typing your own goal selects "Create your own".
      const cur = selectedKeys(g);
      return patch.description?.trim() && !cur.includes(CUSTOM_USE_CASE) ? withKeys(next, [...cur, CUSTOM_USE_CASE]) : next;
    });
  }

  const tooShort = showErrors && !goalReady(goal);

  return (
    <div>
      <StepTitle title="What should your agent do?" description="Pick any that fit, combine a few, or describe it in your own words." />

      <div className="space-y-5">
        <Segmented<Direction>
          label="Call direction"
          value={direction}
          onChange={setDirection}
          options={[
            { value: "outbound", label: "Calls out" },
            { value: "inbound", label: "Answers calls" },
            { value: "both", label: "Both" },
          ]}
        />

        <div>
          {!catalog ? (
            <div className="flex flex-wrap gap-2" aria-hidden>
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-8 w-32 animate-pulse rounded-full bg-zinc-100" />
              ))}
            </div>
          ) : (
            <div role="group" aria-label="Goals (choose any)" className="flex flex-wrap gap-2">
              <Chip
                selected={customOn}
                onClick={() => toggle(CUSTOM_USE_CASE)}
                icon={<PenLine className="h-3 w-3 shrink-0 text-brand-600" />}
                className={cn(!customOn && "border-brand-300 bg-brand-50/40 text-brand-800 hover:border-brand-400 hover:bg-brand-50")}
              >
                Create your own
              </Chip>
              {presets.map((uc) => {
                const on = chosen.includes(uc.key);
                const primary = on && chosen[0] === uc.key && chosen.length > 1;
                return (
                  <Chip key={uc.key} selected={on} onClick={() => toggle(uc.key)} title={uc.description}>
                    {uc.label}
                    {primary && <span className="ml-1.5 rounded bg-brand-600 px-1 py-px text-[10px] font-semibold text-white">Primary</span>}
                  </Chip>
                );
              })}
            </div>
          )}
          {chosen.length > 0 && (
            <p className="mt-2 text-xs text-zinc-500">
              {chosen.length > 1 ? (
                <>
                  Focused on <span className="font-medium text-zinc-700">{labelOf(chosen[0])}</span>, plus {chosen.length - 1} more.
                </>
              ) : (
                all.find((u) => u.key === chosen[0])?.description
              )}
            </p>
          )}
        </div>

        {showCustom && (
          <div className="space-y-2">
            <label htmlFor={`${ids}-desc`} className="block text-sm font-medium text-zinc-800">
              What would you like your AI agent to do?
            </label>
            <VoiceTextarea
              id={`${ids}-desc`}
              rows={5}
              value={description}
              onValue={(v) => setCustom({ description: v })}
              placeholder={CUSTOM_PLACEHOLDER}
              aria-invalid={tooShort}
              className={cn("min-h-28 resize-y", tooShort && "border-red-300")}
            />
            {tooShort && (
              <span className="block text-xs text-red-600" role="alert">
                {description.trim() ? "Add a little more detail — a sentence or two is perfect." : "Pick a goal above or describe what your agent should do."}
              </span>
            )}

            <button
              type="button"
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((v) => !v)}
              className="inline-flex items-center gap-1 rounded-md text-xs font-medium text-zinc-500 hover:text-zinc-800 focus-visible:outline-2 focus-visible:outline-brand-500"
            >
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", detailsOpen && "rotate-180")} />
              Add details (optional)
            </button>
            {detailsOpen && (
              <div className="grid gap-3 sm:grid-cols-3">
                <SmallField id={`${ids}-aud`} label="Who will the agent be speaking with?" placeholder="Homeowners, past clients, buyers…" value={c.audience ?? ""} onChange={(v) => setCustom({ audience: v })} />
                <SmallField id={`${ids}-tone`} label="How should it represent your business?" placeholder="Friendly and conversational…" value={c.tone ?? ""} onChange={(v) => setCustom({ tone: v })} />
                <SmallField id={`${ids}-out`} label="What should the ideal outcome be?" placeholder="Book an appointment, warm transfer…" value={c.outcome ?? ""} onChange={(v) => setCustom({ outcome: v })} />
              </div>
            )}
          </div>
        )}

        {chosen.length > 0 && !customOn && (
          <div className="space-y-1.5">
            <label htmlFor={`${ids}-extra`} className="block text-sm font-medium text-zinc-800">
              Tell us anything specific you&apos;d like your agent to do differently. <span className="font-normal text-zinc-400">(optional)</span>
            </label>
            <VoiceTextarea
              id={`${ids}-extra`}
              rows={3}
              value={goal.extra_instructions ?? ""}
              onValue={(v) => setGoal((g) => ({ ...g, extra_instructions: v }))}
              placeholder={EXTRA_PLACEHOLDER}
              className="resize-y"
            />
          </div>
        )}

        <AssistPanel goal={goal} setGoal={setGoal} canAsk={goalReady(goal)} runAssist={runAssist} />
      </div>
    </div>
  );
}

function SmallField({ id, label, placeholder, value, onChange }: { id: string; label: string; placeholder: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs text-zinc-600">
        {label}
      </label>
      <VoiceInput id={id} value={value} onValue={onChange} placeholder={placeholder} />
    </div>
  );
}
