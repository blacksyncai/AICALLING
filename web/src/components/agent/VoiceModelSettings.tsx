"use client";

import { ChevronDown, Plus, X } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { Field, Input, Select, Toggle } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Agent, ModelCatalog, VoiceCatalog, VoiceTuning } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ModelPicker } from "./ModelPicker";
import { VoicePicker } from "./VoicePicker";

// Used only if /api/settings/models can't be loaded.
const FALLBACK_MODEL_IDS = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "gpt-4.1-nano"];
const FALLBACK_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "multi", label: "Multilingual (auto)" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "pt", label: "Portuguese" },
  { code: "it", label: "Italian" },
  { code: "nl", label: "Dutch" },
  { code: "hi", label: "Hindi" },
  { code: "ja", label: "Japanese" },
];

/** The agent editor's "Voice & Model" tab. Edits the draft only; saving stays with the page. */
export function VoiceModelSettings({
  draft,
  set,
  voices,
}: {
  draft: Agent;
  set: <K extends keyof Agent>(key: K, value: Agent[K]) => void;
  voices: VoiceCatalog | undefined;
}) {
  const { data: models, error: modelsError, isLoading: modelsLoading } = useSWR<ModelCatalog>("/api/settings/models", fetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  const [advanced, setAdvanced] = useState(false);

  const languages = models?.languages?.length ? models.languages : FALLBACK_LANGUAGES;
  const langOptions = languages.some((l) => l.code === draft.language) ? languages : [{ code: draft.language, label: draft.language }, ...languages];
  const traits = [draft.enable_booking && "booking", draft.transfer_number && "transfer"].filter(Boolean) as string[];

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 text-xs font-medium text-zinc-700">Voice</div>
        <VoicePicker
          voices={voices?.voices ?? []}
          featured={voices?.featured ?? []}
          categories={voices?.categories}
          message={voices?.message}
          loading={!voices}
          source={voices?.source}
          value={draft.voice_id}
          speed={draft.voice_speed}
          language={draft.language}
          agentLanguage={draft.language}
          onChange={(id) => set("voice_id", id)}
        />
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Language" hint={draft.language === "multi" ? "Understands and replies in the caller's language." : undefined}>
          <Select value={draft.language} onChange={(e) => set("language", e.target.value)}>
            {langOptions.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </Select>
        </Field>
        <div>
          <div className="mb-1.5 text-xs font-medium text-zinc-700">AI model</div>
          <ModelPicker
            catalog={models}
            loading={modelsLoading}
            error={!!modelsError}
            fallbackIds={FALLBACK_MODEL_IDS}
            value={draft.llm_model}
            onChange={(id) => set("llm_model", id)}
            traits={traits.length ? traits : ["general"]}
          />
          <CallCost model={draft.llm_model} voiceId={draft.voice_id} voices={voices} />
        </div>
        <Field label={`Speaking speed · ${draft.voice_speed.toFixed(2)}x`} className="sm:col-span-2">
          <input
            type="range"
            min={draft.voice_id.startsWith("elevenlabs:") ? 0.8 : 0.7}
            max={draft.voice_id.startsWith("elevenlabs:") ? 1.2 : 1.3}
            step={0.01}
            value={draft.voice_speed}
            onChange={(e) => set("voice_speed", Number(e.target.value))}
            className="w-full accent-brand-600"
          />
        </Field>
      </div>

      <VoiceTuningSettings value={draft.voice_tuning ?? {}} onChange={(v) => set("voice_tuning", v)} />

      <div className="rounded-xl border border-zinc-200">
        <button
          type="button"
          onClick={() => setAdvanced((v) => !v)}
          aria-expanded={advanced}
          aria-controls="voice-advanced"
          className="flex w-full items-center justify-between gap-2 rounded-xl px-4 py-3 text-left text-sm font-medium text-zinc-800 hover:bg-zinc-50"
        >
          <span>
            Advanced settings
            <span className="ml-2 text-xs font-normal text-zinc-500">
              Temperature {draft.temperature.toFixed(1)} · {Math.round(draft.max_duration_seconds / 60)} min max
              {draft.background_audio ? " · Ambience on" : ""}
            </span>
          </span>
          <ChevronDown className={cn("h-4 w-4 shrink-0 text-zinc-400 transition", advanced && "rotate-180")} />
        </button>
        {advanced && (
          <div id="voice-advanced" className="grid gap-5 border-t border-zinc-100 p-4 sm:grid-cols-2">
            <Field
              label={`Creativity (temperature) · ${draft.temperature.toFixed(1)}`}
              hint={draft.llm_model.startsWith("claude-") ? "This model sets its own creativity level." : "Lower = more consistent, higher = more varied."}
            >
              <input
                type="range"
                min={0}
                max={1.2}
                step={0.1}
                value={draft.temperature}
                onChange={(e) => set("temperature", Number(e.target.value))}
                className="w-full accent-brand-600"
              />
            </Field>
            <Field label="Max call length (minutes)">
              <Input
                type="number"
                min={1}
                max={60}
                value={Math.round(draft.max_duration_seconds / 60)}
                onChange={(e) => set("max_duration_seconds", Math.min(60, Math.max(1, Number(e.target.value) || 1)) * 60)}
              />
            </Field>
            <div className="sm:col-span-2">
              <Toggle
                checked={draft.background_audio}
                onChange={(v) => set("background_audio", v)}
                label="Office background ambience"
                description="Plays subtle call-center noise on phone calls so the agent sounds like it's on a sales floor."
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const TUNING_DEFAULTS = { volume: 1, responsiveness: 0.75, interruption: 0.75 };

function Slider({ label, hint, value, min, max, step, format, onChange }: {
  label: string; hint: string; value: number; min: number; max: number; step: number;
  format: (v: number) => string; onChange: (v: number) => void;
}) {
  return (
    <Field label={`${label} · ${format(value)}`} hint={hint}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-brand-600" />
    </Field>
  );
}

/** Volume, turn-taking and pronunciations — all applied by the voice worker on the next call. */
function VoiceTuningSettings({ value, onChange }: { value: VoiceTuning; onChange: (v: VoiceTuning) => void }) {
  const t = { ...TUNING_DEFAULTS, ...value };
  const pron = value.pronunciations ?? [];
  const patch = (p: Partial<VoiceTuning>) => onChange({ ...value, ...p });
  const setPron = (list: { word: string; say: string }[]) => patch({ pronunciations: list });
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <div className="space-y-5 rounded-xl border border-zinc-200 p-4">
      <div className="text-sm font-medium text-zinc-800">Voice tuning</div>
      <div className="grid gap-5 sm:grid-cols-3">
        <Slider label="Volume" hint="How loud the agent speaks." value={t.volume} min={0.5} max={1.5} step={0.05}
          format={(v) => `${v.toFixed(2)}x`} onChange={(v) => patch({ volume: v })} />
        <Slider label="Responsiveness" hint="Higher answers sooner after the caller stops talking." value={t.responsiveness}
          min={0} max={1} step={0.05} format={pct} onChange={(v) => patch({ responsiveness: v })} />
        <Slider label="Interruption sensitivity" hint="Higher lets the caller cut in more easily." value={t.interruption}
          min={0} max={1} step={0.05} format={pct} onChange={(v) => patch({ interruption: v })} />
      </div>
      <div>
        <div className="mb-1 text-xs font-medium text-zinc-700">Pronunciation dictionary</div>
        <p className="mb-2 text-xs text-zinc-500">Spell a word the way it should be said, e.g. BlackSync → Black Sync, Nguyen → Win.</p>
        <div className="space-y-2">
          {pron.map((p, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input aria-label="Word" placeholder="Word" value={p.word} maxLength={60}
                onChange={(e) => setPron(pron.map((x, j) => (j === i ? { ...x, word: e.target.value } : x)))} />
              <span className="text-zinc-400">→</span>
              <Input aria-label="Say it as" placeholder="Say it as" value={p.say} maxLength={120}
                onChange={(e) => setPron(pron.map((x, j) => (j === i ? { ...x, say: e.target.value } : x)))} />
              <button type="button" aria-label="Remove" onClick={() => setPron(pron.filter((_, j) => j !== i))}
                className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700">
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
        {pron.length < 50 && (
          <button type="button" onClick={() => setPron([...pron, { word: "", say: "" }])}
            className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:text-brand-700">
            <Plus className="h-4 w-4" /> Add pronunciation
          </button>
        )}
      </div>
    </div>
  );
}

interface Rates {
  model_rates: Record<string, number>;
  premium_voice_surcharge: number;
  cents_per_credit: number;
}

/** "1.2 credits per minute" for the model and voice being edited (same rule as billing). */
function CallCost({ model, voiceId, voices }: { model: string; voiceId: string; voices: VoiceCatalog | undefined }) {
  const { data } = useSWR<Rates>("/api/billing/rates", fetcher, { revalidateOnFocus: false });
  if (!data) return null;
  const standard = new Set((voices?.voices ?? []).filter((v) => v.category === "standard").map((v) => v.id));
  const premium = !!voices && !!voiceId && !standard.has(voiceId);
  const base = data.model_rates[model] ?? data.model_rates["gpt-4.1-mini"] ?? 1;
  const rate = Math.round((base + (premium ? data.premium_voice_surcharge : 0)) * 1000) / 1000;
  return (
    <p className="mt-1.5 text-xs text-zinc-500">
      Uses <span className="font-medium text-zinc-700">{rate.toLocaleString()} credit{rate === 1 ? "" : "s"} per minute</span> of talk time
      {premium && data.premium_voice_surcharge > 0 ? " (includes premium voice)" : ""}
    </p>
  );
}
