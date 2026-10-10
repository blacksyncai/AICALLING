"use client";

import { Cpu } from "lucide-react";
import { VoicePicker } from "@/components/agent/VoicePicker";
import { Field, Select } from "@/components/ui";
import { Chip, StepTitle } from "./parts";
import { LANGUAGES, RECOMMENDED_MODEL, type Behavior, type VoicesResponse } from "./StepPersonality";

/** Step 5 (optional): voice and language. The model is shown, never swapped behind the user's back. */
export function StepVoice({
  behavior,
  onChange,
  voices,
}: {
  behavior: Behavior;
  onChange: (patch: Partial<Behavior>) => void;
  voices: VoicesResponse | undefined;
}) {
  const choosing = !!behavior.voice_id;
  const language = behavior.language ?? "en";
  return (
    <div className="space-y-5">
      <StepTitle title="Choose a voice (optional)" description="Preview voices and pick one, or keep the recommended voice. You can change it any time." />

      <Field label="Language">
        <Select value={language} onChange={(e) => onChange({ language: e.target.value })} className="sm:w-60">
          {LANGUAGES.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </Select>
      </Field>

      <div role="radiogroup" aria-label="Voice" className="flex flex-wrap gap-2">
        <Chip role="radio" selected={!choosing} onClick={() => onChange({ voice_id: "" })}>
          Recommended voice
        </Chip>
        <Chip role="radio" selected={choosing} onClick={() => !choosing && onChange({ voice_id: voices?.featured?.[0]?.id ?? voices?.voices?.[0]?.id ?? "" })}>
          Choose a voice
        </Chip>
      </div>
      {choosing && (
        <VoicePicker
          voices={voices?.voices ?? []}
          featured={voices?.featured ?? []}
          loading={!voices}
          source={voices?.source}
          value={behavior.voice_id ?? ""}
          speed={1}
          language={language}
          onChange={(id) => onChange({ voice_id: id })}
          inline
        />
      )}

      <div className="flex items-start gap-2 rounded-lg bg-zinc-100/70 px-3 py-2 text-xs text-zinc-600">
        <Cpu className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" />
        <span>
          <span className="font-medium text-zinc-800">Runs on {behavior.llm_model || RECOMMENDED_MODEL}.</span> Every voice here works with it; if a voice
          doesn&apos;t support your language we&apos;ll tell you rather than switching anything. You can change the model in the agent editor.
        </span>
      </div>
    </div>
  );
}
