"use client";

import { Pencil, Sparkles } from "lucide-react";
import { useState } from "react";
import { VoiceTextarea } from "@/components/MicButton";
import { Field, Input, Select } from "@/components/ui";
import { SOMETHING_ELSE, type BuilderCatalog, type DraftData, type DraftGoal, type Specialty } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { MIN_DESCRIPTION } from "./goal";
import { Chip, Segmented, StepTitle, industryIcon } from "./parts";
import { LANGUAGES, type Behavior, type VoicesResponse } from "./StepPersonality";
import { VoiceCards } from "./VoiceCards";

type Business = NonNullable<DraftData["business"]>;
type Direction = NonNullable<DraftGoal["direction"]>;

export const NAME_SUGGESTIONS = ["Maya", "Ethan", "Ava", "Jordan", "Olivia"];

const DIRECTIONS: { value: Direction; label: string }[] = [
  { value: "outbound", label: "Calls out" },
  { value: "inbound", label: "Answers calls" },
  { value: "both", label: "Both" },
];

export function specialtiesFor(catalog: BuilderCatalog | undefined, industry: string | undefined): Specialty[] {
  const s = catalog?.specialties ?? {};
  return s[industry ?? ""] ?? s.other ?? [];
}

/** Step 1 — Meet your new agent: what it does, its name and its voice. */
export function StepIdentity({
  business,
  onBusiness,
  goal,
  setGoal,
  behavior,
  onBehavior,
  catalog,
  voices,
  showErrors,
}: {
  business: Business;
  onBusiness: (p: Partial<Business>) => void;
  goal: DraftGoal;
  setGoal: (fn: (g: DraftGoal) => DraftGoal) => void;
  behavior: Behavior;
  onBehavior: (p: Partial<Behavior>) => void;
  catalog: BuilderCatalog | undefined;
  voices: VoicesResponse | undefined;
  showErrors: boolean;
}) {
  const [changingIndustry, setChangingIndustry] = useState(!business.industry);
  // Asked only when the business profile doesn't have it yet (kept visible while typing).
  const [askName] = useState(!business.name?.trim());
  const industry = catalog?.industries.find((i) => i.key === business.industry);
  const specialties = specialtiesFor(catalog, business.industry);
  const sp = goal.specialty;
  const other = sp?.key === SOMETHING_ELSE;
  const recommended = sp && !other ? sp.direction : undefined;
  const otherText = sp?.description ?? "";

  function pick(s: Specialty) {
    setGoal((g) => ({
      ...g,
      specialty: { ...s },
      // Follow the specialty's direction unless the customer already chose one.
      direction: g.direction_set ? g.direction : s.direction,
      // A different specialty means a different mission.
      ...(g.specialty?.key !== s.key && g.mission_source !== "user" ? { mission: "", mission_source: undefined } : {}),
    }));
  }

  function pickOther() {
    setGoal((g) => ({
      ...g,
      specialty: { key: SOMETHING_ELSE, label: "", direction: g.direction ?? "outbound", use_cases: [], description: g.specialty?.description ?? "" },
      ...(g.specialty?.key !== SOMETHING_ELSE && g.mission_source !== "user" ? { mission: "", mission_source: undefined } : {}),
    }));
  }

  const name = behavior.agent_name ?? "";

  return (
    <div>
      <StepTitle title="Meet your new agent" description="Pick its specialty, give it a name and choose how it sounds." />

      <div className="space-y-7">
        {/* Industry (a default from the business profile, not a restriction) */}
        {changingIndustry || !industry ? (
          <div>
            <span className="mb-1.5 block text-xs font-medium text-zinc-700">Your industry</span>
            {!catalog ? (
              <div className="h-10 animate-pulse rounded-lg bg-zinc-100" />
            ) : (
              <div role="radiogroup" aria-label="Industry" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {catalog.industries.map((ind) => {
                  const Icon = industryIcon(ind.icon, ind.key);
                  const selected = business.industry === ind.key;
                  return (
                    <button
                      key={ind.key}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => {
                        onBusiness({ industry: ind.key });
                        if (business.industry !== ind.key) setGoal((g) => ({ ...g, specialty: undefined, mission: g.mission_source === "user" ? g.mission : "" }));
                        setChangingIndustry(false);
                      }}
                      className={cn(
                        "flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs font-medium transition focus-visible:outline-2 focus-visible:outline-brand-500",
                        selected ? "border-brand-500 bg-brand-50/60 text-brand-800 ring-1 ring-brand-500" : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300",
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", selected ? "text-brand-600" : "text-zinc-400")} />
                      <span className="truncate">{ind.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
            {showErrors && !business.industry && <span className="mt-1 block text-xs text-red-600">Please pick the closest match.</span>}
          </div>
        ) : null}

        {/* Specialty */}
        <section>
          <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-zinc-900">What kind of agent are we building?</h3>
              <p className="mt-0.5 text-xs text-zinc-500">Choose what your agent will specialize in.</p>
            </div>
            {industry && !changingIndustry && (
              <button
                type="button"
                onClick={() => setChangingIndustry(true)}
                className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-800"
              >
                {industry.label} <Pencil className="h-3 w-3" />
              </button>
            )}
          </div>
          {!catalog ? (
            <div className="flex flex-wrap gap-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-8 w-32 animate-pulse rounded-full bg-zinc-100" />
              ))}
            </div>
          ) : (
            <div role="radiogroup" aria-label="Specialty" className="flex flex-wrap gap-2">
              {specialties.map((s) => (
                <Chip key={s.key} role="radio" selected={sp?.key === s.key} onClick={() => pick(s)}>
                  {s.label}
                </Chip>
              ))}
              <Chip role="radio" selected={other} onClick={pickOther} icon={<Sparkles className="h-3 w-3 text-brand-600" />}>
                Something else
              </Chip>
            </div>
          )}
          {other && (
            <div className="mt-3">
              <VoiceTextarea
                rows={2}
                value={otherText}
                onValue={(v) => setGoal((g) => ({ ...g, specialty: { ...g.specialty!, description: v } }))}
                placeholder="In your own words, e.g. Call past clients to ask for reviews and referrals."
                aria-label="Describe your agent"
              />
              {showErrors && otherText.trim().length < MIN_DESCRIPTION && (
                <span className="mt-1 block text-xs text-red-600">Describe it in a sentence so we know what to build.</span>
              )}
            </div>
          )}
          {showErrors && !sp && <span className="mt-1 block text-xs text-red-600">Pick what your agent will do.</span>}

          {sp && (
            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-xs text-zinc-600">
                {recommended ? (
                  <>
                    Recommended for {sp.label}: <span className="font-medium text-zinc-900">{DIRECTIONS.find((d) => d.value === recommended)?.label}</span>
                  </>
                ) : (
                  "How will it talk to people?"
                )}
              </span>
              <Segmented
                label="Call direction"
                value={goal.direction ?? recommended ?? "outbound"}
                options={DIRECTIONS}
                onChange={(v) => setGoal((g) => ({ ...g, direction: v, direction_set: true }))}
              />
            </div>
          )}
        </section>

        {/* Name */}
        <section>
          <h3 className="mb-2 text-sm font-semibold text-zinc-900">What should we call your agent?</h3>
          <Input value={name} onChange={(e) => onBehavior({ agent_name: e.target.value })} placeholder="e.g. Maya" maxLength={40} aria-label="Agent name" />
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-zinc-400">Try</span>
            {NAME_SUGGESTIONS.map((n) => (
              <Chip key={n} role="radio" selected={name === n} onClick={() => onBehavior({ agent_name: n })}>
                {n}
              </Chip>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-zinc-500">Leave it blank and we&apos;ll pick one. The specialty shows as a badge next to the name.</p>
        </section>

        {/* Voice */}
        <section>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-zinc-900">Choose your agent&apos;s voice</h3>
              <p className="mt-0.5 text-xs text-zinc-500">Give your agent a voice that fits your business.</p>
            </div>
            <Select
              aria-label="Language"
              value={behavior.language ?? "en"}
              onChange={(e) => onBehavior({ language: e.target.value })}
              className="h-8 w-auto py-0 text-xs"
            >
              {LANGUAGES.map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </Select>
          </div>
          <VoiceCards voices={voices} value={behavior.voice_id ?? ""} language={behavior.language ?? "en"} onChange={(id) => onBehavior({ voice_id: id })} />
        </section>

        {askName && (
          <Field label="Business name" hint="Your agent introduces itself on behalf of this business.">
            <Input
              value={business.name ?? ""}
              onChange={(e) => onBusiness({ name: e.target.value })}
              placeholder="e.g. Acme Realty"
              aria-invalid={showErrors && !business.name?.trim()}
            />
            {showErrors && !business.name?.trim() && <span className="mt-1 block text-xs text-red-600">Please enter your business name.</span>}
          </Field>
        )}
      </div>
    </div>
  );
}
