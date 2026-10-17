"use client";

import { ChevronDown, Plus, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { createPortal } from "react-dom";
import { Field, Input, Modal, Select, Toggle } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Agent, ModelCatalog, VoiceCatalog, VoiceTuning } from "@/lib/types";
import { ModelPicker } from "./ModelPicker";
import { VoicePicker } from "./VoicePicker";

// Used only if /api/settings/models can't be loaded.
const FALLBACK_MODEL_IDS = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "gpt-4.1-nano"];
const FALLBACK_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "multi", label: "Multilingual (auto)" },
  { code: "ar", label: "Arabic" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "pt", label: "Portuguese" },
  { code: "it", label: "Italian" },
  { code: "nl", label: "Dutch" },
  { code: "hi", label: "Hindi" },
  { code: "ja", label: "Japanese" },
];

const LANGUAGE_FLAGS: Record<string, string> = {
  en: "🇺🇸", es: "🇪🇸", fr: "🇫🇷", de: "🇩🇪", pt: "🇵🇹", it: "🇮🇹", nl: "🇳🇱",
  hi: "🇮🇳", ja: "🇯🇵", zh: "🇨🇳", ko: "🇰🇷", ru: "🇷🇺", ar: "🇸🇦", tr: "🇹🇷",
  sv: "🇸🇪", pl: "🇵🇱", uk: "🇺🇦", multi: "🌐",
};

/** Separate Voice and Model / Brain tabs share the existing saved draft. */
export function VoiceModelSettings({ draft, set, voices, view = "voice" }: {
  draft: Agent;
  set: <K extends keyof Agent>(key: K, value: Agent[K]) => void;
  voices: VoiceCatalog | undefined;
  view?: "voice" | "model";
}) {
  const { data: models, error: modelsError, isLoading: modelsLoading } = useSWR<ModelCatalog>("/api/settings/models", fetcher, {
    revalidateOnFocus: false, shouldRetryOnError: false,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const settingsContent = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!settingsOpen) return;
    const frame = requestAnimationFrame(() => settingsContent.current?.querySelector<HTMLInputElement>("input")?.focus());
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const dialog = settingsContent.current?.closest('[role="dialog"]');
      const controls = dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]');
      if (!controls?.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (!dialog?.contains(document.activeElement) || (!event.shiftKey && document.activeElement === last)) {
        event.preventDefault(); first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      }
    };
    document.addEventListener("keydown", trapFocus);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", trapFocus);
      settingsButton.current?.focus();
    };
  }, [settingsOpen]);
  const languages = models?.languages?.length ? models.languages : FALLBACK_LANGUAGES;
  const langOptions = languages.some((l) => l.code === draft.language) ? languages : [{ code: draft.language, label: draft.language }, ...languages];
  const traits = [draft.enable_booking && "booking", draft.transfer_number && "transfer"].filter(Boolean) as string[];

  if (view === "model") return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-zinc-900">Your agent’s brain</h3>
        <p className="mt-1 text-sm text-zinc-500">Choose the intelligence behind the conversation.</p>
      </div>
      <div>
        <div className="mb-1.5 text-xs font-medium text-zinc-700">AI model</div>
        <ModelPicker inline catalog={models} loading={modelsLoading} error={!!modelsError} fallbackIds={FALLBACK_MODEL_IDS}
          value={draft.llm_model} onChange={(id) => set("llm_model", id)} traits={traits.length ? traits : ["general"]} />
        <CallCost model={draft.llm_model} voiceId={draft.voice_id} voices={voices} />
      </div>
      <div className="grid gap-5 rounded-xl border border-zinc-200 p-4 sm:grid-cols-2">
        <Field label={`Creativity (temperature) · ${draft.temperature.toFixed(1)}`}
          hint={draft.llm_model.startsWith("claude-") ? "This model sets its own creativity level." : "Lower = more consistent, higher = more varied."}>
          <input type="range" min={0} max={1.2} step={0.1} value={draft.temperature}
            onChange={(e) => set("temperature", Number(e.target.value))} className="w-full accent-brand-600" />
        </Field>
        <Field label="Max call length (minutes)">
          <Input type="number" min={1} max={60} value={Math.round(draft.max_duration_seconds / 60)}
            onChange={(e) => set("max_duration_seconds", Math.min(60, Math.max(1, Number(e.target.value) || 1)) * 60)} />
        </Field>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="mb-1.5 text-xs font-medium text-zinc-700">Voice</div>
      <VoicePicker voices={voices?.voices ?? []} featured={voices?.featured ?? []} categories={voices?.categories}
        message={voices?.message} loading={!voices} source={voices?.source} value={draft.voice_id}
        speed={draft.voice_speed} language={draft.language} agentLanguage={draft.language}
        onChange={(id) => { set("voice_id", id); if (id === "elevenlabs:Ywuz3KyW2N5pqKNpwcCL") set("language", "ar"); }} inline defaultOpen keepOpen suspendDismiss={settingsOpen}
        headerAccessory={
          <div className="flex shrink-0 items-stretch gap-2">
            <div className="relative flex w-14 items-center justify-center rounded-xl border border-zinc-200 bg-white px-2 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100 sm:w-36"
              title={`Agent language: ${langOptions.find((l) => l.code === draft.language)?.label || draft.language}`}>
              <span aria-hidden="true" className="flex min-w-0 items-center gap-1.5 text-sm text-zinc-700">
                <span className="text-lg">{LANGUAGE_FLAGS[draft.language] || "🌐"}</span>
                <span className="hidden truncate sm:inline">{langOptions.find((l) => l.code === draft.language)?.label || draft.language}</span>
                <ChevronDown className="h-3 w-3 shrink-0" />
              </span>
              <Select aria-label="Agent language" value={draft.language} onChange={(e) => set("language", e.target.value)}
                className="absolute inset-0 h-full! cursor-pointer opacity-0">
                {langOptions.map((l) => <option key={l.code} value={l.code}>{LANGUAGE_FLAGS[l.code] || "🌐"} {l.label}</option>)}
              </Select>
            </div>
            <button ref={settingsButton} type="button" aria-label="Voice settings" title="Voice settings" onClick={() => setSettingsOpen(true)}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-200 px-3 text-sm font-medium text-zinc-600 transition hover:border-brand-400 hover:text-brand-600 focus-visible:outline-2 focus-visible:outline-brand-500">
              <SlidersHorizontal className="h-4 w-4" /><span className="hidden lg:inline">Voice settings</span>
            </button>
          </div>
        } />
      {draft.language === "multi" && <p className="text-xs text-zinc-500">Understands and replies in the caller’s language.</p>}
      {settingsOpen && createPortal(<Modal open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Voice settings" wide>
        <div ref={settingsContent} className="space-y-5">
          <p className="text-sm text-zinc-500">Fine-tune delivery. Changes save with your agent.</p>
          <Field label={`Speaking speed · ${draft.voice_speed.toFixed(2)}x`}>
            <input type="range" min={draft.voice_id.startsWith("elevenlabs:") ? 0.8 : 0.7}
              max={draft.voice_id.startsWith("elevenlabs:") ? 1.2 : 1.3} step={0.01} value={draft.voice_speed}
              onChange={(e) => set("voice_speed", Number(e.target.value))} className="w-full accent-brand-600" />
          </Field>
          <VoiceTuningSettings value={draft.voice_tuning ?? {}} onChange={(v) => set("voice_tuning", v)} />
          <Toggle checked={draft.background_audio} onChange={(v) => set("background_audio", v)}
            label="Office background ambience" description="Plays subtle call-center noise on phone calls so the agent sounds like it's on a sales floor." />
        </div>
      </Modal>, document.body)}
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
