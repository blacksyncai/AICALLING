"use client";

import { Cpu, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { VoicePicker } from "@/components/agent/VoicePicker";
import { Field, Input, Notice, Select, Toggle } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { BuilderCatalog, DraftData } from "@/lib/builder";
import type { Voice } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, Collapsible, Segmented } from "./parts";

export type Behavior = NonNullable<DraftData["behavior"]>;
type Depth = NonNullable<Behavior["qualification_depth"]>;

export const LANGUAGES: [string, string][] = [
  ["en", "English"],
  ["ar", "Arabic"],
  ["es", "Spanish"],
  ["fr", "French"],
  ["de", "German"],
  ["pt", "Portuguese"],
  ["multi", "Multilingual"],
];

export const RECOMMENDED_MODEL = "our recommended model";

/** A model's display name (never its raw id). */
export function useModelName(id: string | undefined | null): string {
  const { data } = useSWR<{ models: { id: string; name: string }[] }>(id ? "/api/settings/models" : null, fetcher, { revalidateOnFocus: false });
  if (!id) return RECOMMENDED_MODEL;
  return data?.models.find((m) => m.id === id)?.name ?? "the agent's model";
}
export const MODEL_NOTE = "We'll use the recommended model; change it anytime in the agent editor.";

export type VoicesResponse = { source: string; voices: Voice[]; featured?: Voice[] };

export function bookingStatus(catalog: BuilderCatalog | undefined) {
  return catalog?.integrations.find((i) => i.key === "calcom")?.status;
}

/** The "Customize now" half of the Fine-tune step: name, voice, style and what happens on the call. */
export function PersonalityFields({
  behavior,
  onChange,
  catalog,
  voices,
  transferOn,
  setTransferOn,
  showErrors,
  compact = false,
}: {
  behavior: Behavior;
  onChange: (patch: Partial<Behavior>) => void;
  catalog: BuilderCatalog | undefined;
  voices?: VoicesResponse | undefined;
  transferOn: boolean;
  setTransferOn: (v: boolean) => void;
  showErrors: boolean;
  /** The wizard asks for name, language, voice and model on their own steps. */
  compact?: boolean;
}) {
  const booking = bookingStatus(catalog);
  const styles = catalog?.styles ?? [];
  const numberMissing = showErrors && transferOn && !behavior.transfer_number?.trim();
  const [pickVoice, setPickVoice] = useState(!!behavior.voice_id);

  return (
    <div className="space-y-5">
      {!compact && (
        <>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Agent name" hint="Leave empty and AI will pick one.">
          <Input value={behavior.agent_name ?? ""} onChange={(e) => onChange({ agent_name: e.target.value })} placeholder="e.g. Sarah" />
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
        <div role="radiogroup" aria-label="Voice" className="flex flex-wrap gap-2">
          <Chip
            role="radio"
            selected={!pickVoice}
            onClick={() => {
              setPickVoice(false);
              onChange({ voice_id: "" });
            }}
          >
            Default · Marissa
          </Chip>
          <Chip role="radio" selected={pickVoice} onClick={() => setPickVoice(true)}>
            Choose a voice
          </Chip>
        </div>
        {pickVoice && (
          <div className="mt-3">
            <VoicePicker
              voices={voices?.voices ?? []}
              featured={voices?.featured ?? []}
              loading={!voices}
              source={voices?.source}
              value={behavior.voice_id ?? ""}
              speed={1}
              language={behavior.language ?? "en"}
              onChange={(id) => onChange({ voice_id: id, ...(id === "elevenlabs:Ywuz3KyW2N5pqKNpwcCL" ? { language: "ar" } : {}) })}
            />
          </div>
        )}
      </div>

      <div className="flex items-start gap-2 rounded-lg bg-zinc-100/70 px-3 py-2 text-xs text-zinc-600">
        <Cpu className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" />
        <span>
          <span className="font-medium text-zinc-800">AI model: {RECOMMENDED_MODEL}.</span> {MODEL_NOTE}
        </span>
      </div>

        </>
      )}

      {styles.length > 0 && (
        <div>
          <span className="mb-1.5 block text-xs font-medium text-zinc-700">Conversation style</span>
          <div role="radiogroup" aria-label="Conversation style" className="flex flex-wrap gap-2">
            <Chip role="radio" selected={!behavior.style} onClick={() => onChange({ style: "" })} title="Follows the tone you described, or friendly by default.">
              Match my goal
            </Chip>
            {styles.map((s) => (
              <Chip key={s.key} role="radio" selected={behavior.style === s.key} onClick={() => onChange({ style: s.key })} title={s.description}>
                {s.label}
              </Chip>
            ))}
          </div>
          {behavior.style === "custom" && (
            <Input
              className="mt-2"
              aria-label="Describe the tone"
              value={behavior.custom_style ?? ""}
              onChange={(e) => onChange({ custom_style: e.target.value })}
              placeholder="e.g. Calm, warm and never pushy"
            />
          )}
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
          <div className="rounded-lg border border-dashed border-zinc-200 p-3 opacity-70">
            <span className="block text-sm font-medium text-zinc-700">Book appointments</span>
            <span className="mt-0.5 block text-xs text-zinc-500">Calendar booking isn&apos;t available on your account yet.</span>
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
              <Input value={behavior.transfer_when ?? ""} onChange={(e) => onChange({ transfer_when: e.target.value })} placeholder="e.g. They're ready to talk to an agent" />
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
            <SlidersHorizontal className="h-4 w-4 text-zinc-400" /> Advanced
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
  );
}
