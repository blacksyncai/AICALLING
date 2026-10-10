"use client";

import { Plug } from "lucide-react";
import type { BuilderCatalog, DraftData } from "@/lib/builder";
import { Collapsible, Segmented, StepTitle } from "./parts";
import { MODEL_NOTE, PersonalityFields, RECOMMENDED_MODEL, bookingStatus, type Behavior, type VoicesResponse } from "./StepPersonality";
import { ToolsPicker } from "./StepTools";

type Mode = "later" | "now";

/** "I'll decide later" unless the user chose to customize (older drafts with settings count as customized). */
export function decidesLater(behavior: Behavior | undefined): boolean {
  const b = behavior ?? {};
  if (b.decide_later !== undefined) return b.decide_later;
  // Same keys as uses_recommended_settings() in backend/app/agent/generator.py.
  return !(
    ["agent_name", "voice_id", "style", "booking", "transfer_number", "transfer_when", "callback", "ai_disclosure", "qualification_depth"] as const
  ).some((k) => b[k] !== undefined);
}

/** Recommended settings, in plain words, for the review and the "decide later" summary. */
export function recommendedRows(catalog: BuilderCatalog | undefined, bookingLikely: boolean): [string, string][] {
  const calendar = bookingStatus(catalog) === "available";
  return [
    ["Voice", "Recommended voice"],
    ["AI model", `${RECOMMENDED_MODEL} (recommended)`],
    ["Booking", bookingLikely ? (calendar ? "On — books into your calendar" : "Off until your calendar is connected") : "Off for this goal"],
    ["Transfers", "Off — add a number in the agent editor"],
    ["Tools & CRM", "None for now"],
    ["Says it's an AI", "Yes"],
  ];
}

export function StepFineTune({
  behavior,
  onChange,
  catalog,
  voices,
  transferOn,
  setTransferOn,
  showErrors,
  tools,
  onToolsChange,
  industry,
  bookingLikely,
}: {
  behavior: Behavior;
  onChange: (patch: Partial<Behavior>) => void;
  catalog: BuilderCatalog | undefined;
  voices: VoicesResponse | undefined;
  transferOn: boolean;
  setTransferOn: (v: boolean) => void;
  showErrors: boolean;
  tools: string[];
  onToolsChange: (next: string[]) => void;
  industry: string | undefined;
  bookingLikely: boolean;
}) {
  const later = decidesLater(behavior);

  function setMode(m: Mode) {
    if (m === "later") return onChange({ decide_later: true });
    const calendar = bookingStatus(catalog) === "available";
    onChange({
      language: "en",
      qualification_depth: "standard",
      booking: calendar && bookingLikely,
      callback: true,
      ai_disclosure: true,
      ...behavior,
      decide_later: false,
    });
  }

  return (
    <div>
      <StepTitle title="Fine-tune (optional)" description="Everything has a recommended default. You can change any of it later." />

      <div className="space-y-5">
        <Segmented<Mode>
          label="Settings"
          value={later ? "later" : "now"}
          onChange={setMode}
          options={[
            { value: "later", label: "I'll decide later" },
            { value: "now", label: "Customize now" },
          ]}
        />

        {later ? (
          <div className="space-y-2">
            <dl className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 bg-white px-4">
              {recommendedRows(catalog, bookingLikely).map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-4">
                  <dt className="shrink-0 text-xs text-zinc-500 sm:w-28 sm:pt-0.5">{k}</dt>
                  <dd className="text-sm text-zinc-900">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="text-xs text-zinc-500">{MODEL_NOTE}</p>
          </div>
        ) : (
          <>
            <PersonalityFields
              behavior={behavior}
              onChange={onChange}
              catalog={catalog}
              voices={voices}
              transferOn={transferOn}
              setTransferOn={setTransferOn}
              showErrors={showErrors}
            />
            <Collapsible
              defaultOpen={tools.length > 0}
              title={
                <>
                  <Plug className="h-4 w-4 text-zinc-400" /> Tools and CRM
                </>
              }
              meta={tools.length ? `${tools.length} selected` : "Optional"}
            >
              <ToolsPicker selected={tools} onChange={onToolsChange} catalog={catalog} industry={industry} />
            </Collapsible>
          </>
        )}
      </div>
    </div>
  );
}
