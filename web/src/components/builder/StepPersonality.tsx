"use client";

import { SlidersHorizontal } from "lucide-react";
import { VoicePicker } from "@/components/agent/VoicePicker";
import { Field, Input, Notice, Select, Toggle } from "@/components/ui";
import type { BuilderCatalog, DraftData } from "@/lib/builder";
import type { Voice } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Collapsible, OptionCard, Segmented, StepTitle } from "./parts";

type Behavior = NonNullable<DraftData["behavior"]>;
type Depth = NonNullable<Behavior["qualification_depth"]>;

export const LANGUAGES: [string, string][] = [
  ["en", "English"],
  ["es", "Spanish"],
  ["fr", "French"],
  ["de", "German"],
  ["pt", "Portuguese"],
  ["multi", "Multilingual"],
];

export type VoicesResponse = { source: string; voices: Voice[]; featured?: Voice[] };

export function bookingStatus(catalog: BuilderCatalog | undefined) {
  return catalog?.integrations.find((i) => i.key === "calcom")?.status;
}

export function StepPersonality({
  behavior,
  onChange,
  catalog,
  voices,
  transferOn,
  setTransferOn,
  showErrors,
}: {
  behavior: Behavior;
  onChange: (patch: Partial<Behavior>) => void;
  catalog: BuilderCatalog | undefined;
  voices: VoicesResponse | undefined;
  transferOn: boolean;
  setTransferOn: (v: boolean) => void;
  showErrors: boolean;
}) {
  const booking = bookingStatus(catalog);
  const styles = catalog?.styles ?? [];
  const nameMissing = showErrors && !behavior.agent_name?.trim();
  const numberMissing = showErrors && transferOn && !behavior.transfer_number?.trim();

  return (
    <div>
      <StepTitle title="Give your agent a personality" description="How it sounds and how it handles the conversation." />

      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Agent name" hint="What it calls itself on the phone.">
            <Input
              value={behavior.agent_name ?? ""}
              onChange={(e) => onChange({ agent_name: e.target.value })}
              placeholder="e.g. Sarah"
              aria-invalid={nameMissing}
              className={cn(nameMissing && "border-red-300")}
            />
            {nameMissing && <span className="mt-1 block text-xs text-red-600">Please give your agent a name.</span>}
          </Field>
          <Field label="Language">
            <Select value={behavior.language ?? "en"} onChange={(e) => onChange({ language: e.target.value })}>
              {LANGUAGES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div>
          <span className="mb-1.5 block text-xs font-medium text-zinc-700">Voice</span>
          <VoicePicker
            voices={voices?.voices ?? []}
            featured={voices?.featured ?? []}
            loading={!voices}
            source={voices?.source}
            value={behavior.voice_id ?? ""}
            speed={1}
            language={behavior.language ?? "en"}
            onChange={(id) => onChange({ voice_id: id })}
          />
        </div>

        {styles.length > 0 && (
          <div>
            <span className="mb-1.5 block text-xs font-medium text-zinc-700">Conversation style</span>
            <div role="radiogroup" aria-label="Conversation style" className="grid gap-2 sm:grid-cols-2">
              {styles.map((s) => (
                <OptionCard key={s.key} selected={behavior.style === s.key} onClick={() => onChange({ style: s.key })} title={s.label} description={s.description} />
              ))}
            </div>
          </div>
        )}

        <div className="space-y-2">
          <span className="block text-xs font-medium text-zinc-700">During the call</span>
          {booking && booking !== "coming_soon" ? (
            <>
              <Toggle
                label="Book appointments"
                description="Your agent can check your calendar and book a time while on the call."
                checked={!!behavior.booking}
                onChange={(v) => onChange({ booking: v })}
              />
              {booking === "needs_setup" && behavior.booking && (
                <Notice tone="amber">Connect your calendar in Integrations before going live — until then, your agent will offer a callback instead.</Notice>
              )}
            </>
          ) : (
            <div className="flex items-start justify-between gap-4 rounded-lg border border-dashed border-zinc-200 p-3 opacity-70">
              <span>
                <span className="block text-sm font-medium text-zinc-700">Book appointments</span>
                <span className="mt-0.5 block text-xs text-zinc-500">Calendar booking isn&apos;t available on your account yet.</span>
              </span>
            </div>
          )}

          <Toggle
            label="Transfer to a person"
            description="Hand the call to your team when the caller is ready or asks for someone."
            checked={transferOn}
            onChange={setTransferOn}
          />
          {transferOn && (
            <div className="grid gap-3 rounded-lg border border-zinc-200 bg-zinc-50/60 p-3 sm:grid-cols-2">
              <Field label="Transfer to this number">
                <Input
                  type="tel"
                  inputMode="tel"
                  value={behavior.transfer_number ?? ""}
                  onChange={(e) => onChange({ transfer_number: e.target.value })}
                  placeholder="+1 512 555 0100"
                  aria-invalid={numberMissing}
                  className={cn(numberMissing && "border-red-300")}
                />
                {numberMissing && <span className="mt-1 block text-xs text-red-600">Add the number to transfer to.</span>}
              </Field>
              <Field label="Transfer when">
                <Input
                  value={behavior.transfer_when ?? ""}
                  onChange={(e) => onChange({ transfer_when: e.target.value })}
                  placeholder="e.g. They're ready to get a quote"
                />
              </Field>
            </div>
          )}

          <Toggle
            label="Say it's an AI assistant"
            description="Your agent mentions it's an AI at the start of the call. Required in some places, and it builds trust."
            checked={behavior.ai_disclosure !== false}
            onChange={(v) => onChange({ ai_disclosure: v })}
          />
        </div>

        <Collapsible
          title={
            <>
              <SlidersHorizontal className="h-4 w-4 text-zinc-400" /> More options
            </>
          }
        >
          <div className="space-y-4">
            <div>
              <span className="mb-1.5 block text-xs font-medium text-zinc-700">How many questions should it ask?</span>
              <Segmented<Depth>
                label="Qualification depth"
                value={behavior.qualification_depth ?? "standard"}
                onChange={(v) => onChange({ qualification_depth: v })}
                options={[
                  { value: "light", label: "Light" },
                  { value: "standard", label: "Standard" },
                  { value: "thorough", label: "Thorough" },
                ]}
              />
              <p className="mt-1.5 text-xs text-zinc-500">
                {behavior.qualification_depth === "light"
                  ? "Just the essentials — quick, low-pressure calls."
                  : behavior.qualification_depth === "thorough"
                    ? "Asks more questions so your team gets the full picture."
                    : "A balanced set of questions for most businesses."}
              </p>
            </div>
            <Toggle
              label="Offer callbacks"
              description="If it's a bad time, your agent offers to call back later."
              checked={behavior.callback !== false}
              onChange={(v) => onChange({ callback: v })}
            />
          </div>
        </Collapsible>
      </div>
    </div>
  );
}
