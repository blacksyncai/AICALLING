"use client";

import { voicePreview } from "@/lib/voice-preview";

import {
  Check,
  ChevronRight,
  Library,
  Loader2,
  Pause,
  Play,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { VoicePicker } from "@/components/agent/VoicePicker";
import {
  baseLanguage,
  capitalize,
  languageName,
} from "@/components/agent/picker-utils";
import { Badge, Button, Modal } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Voice } from "@/lib/types";
import { cn } from "@/lib/utils";
import { VoiceAvatar } from "@/components/ui/voice-avatar";
import styles from "@/components/agent/voice-chooser.module.css";
import type { VoicesResponse } from "./StepPersonality";

const PREVIEW_LINE =
  "Hey there, this is a quick preview of how I'll sound on your calls. Does this work for you?";

/** House suggestions in display order; Mia is the third option. */
export const HOUSE_VOICES = [
  "fishaudio:v_SriZAPqzgffq",
  "fishaudio:v_goYxyDbAUbfP",
  "26def8d4-b397-4d79-b5f1-d554d16ba4fe",
  "91e4713f-2150-4be6-8564-2d121bbd8c10",
  "lkcartesia:v_ZMqDxhK7B6i6",
];

/**
 * Four voices to show up front, in a stable order so cards never jump around when one is picked:
 * The house voices first, then others in the agent's language. A chosen voice that isn't among them
 * takes the last slot.
 */
export function suggestedVoices(
  voices: VoicesResponse | undefined,
  language: string,
  selected: string,
  pinned: string[] = [],
): Voice[] {
  const all = [...(voices?.featured ?? []), ...(voices?.voices ?? [])];
  const seen = new Set<string>();
  const unique = all.filter((v) =>
    seen.has(v.id) ? false : (seen.add(v.id), true),
  );
  const lang = baseLanguage(language);
  const fits = (v: Voice) => !v.language || baseLanguage(v.language) === lang;
  const featured = (voices?.featured ?? []).filter(fits);
  const pool = featured.length ? featured : unique.filter(fits);
  const standard = pool.filter((v) => v.category !== "premium");
  const premium = pool.filter((v) => v.category === "premium");
  const byId = (id: string) => unique.find((v) => v.id === id);
  const fixed = [...HOUSE_VOICES, ...pinned]
    .map(byId)
    .filter((v): v is Voice => !!v);
  const ids = new Set<string>();
  const out = [...fixed, ...standard, ...premium]
    .filter((v) => (ids.has(v.id) ? false : (ids.add(v.id), true)))
    .slice(0, 4);
  const chosen = byId(selected);
  if (chosen && !out.some((v) => v.id === chosen.id)) {
    if (out.length < 4) out.push(chosen);
    else out[3] = chosen;
  }
  return out;
}

function usePreview(language: string) {
  const [playing, setPlaying] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const cache = useRef(new Map<string, string>());
  const token = useRef(0);

  const stop = useCallback(() => {
    token.current++;
    audio.current?.pause();
    audio.current = null;
    setPlaying(null);
    setLoading(null);
  }, []);

  useEffect(() => stop, [stop]);

  async function toggle(v: Voice) {
    setError("");
    if (playing === v.id || loading === v.id) return stop();
    stop();
    const t = token.current;
    const preview = voicePreview(v.language, language, PREVIEW_LINE);
    const key = `${v.id}|${preview.language}`;
    try {
      let url = cache.current.get(key);
      if (!url) {
        setLoading(v.id);
        const res = await fetch("/api/settings/voices/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            voice_id: v.id,
            text: preview.text,
            speed: 1,
            language: preview.language,
          }),
        });
        if (!res.ok)
          throw new Error(
            (await res.json().catch(() => ({}))).detail ?? "Preview failed",
          );
        url = URL.createObjectURL(await res.blob());
        cache.current.set(key, url);
      }
      if (t !== token.current) return;
      const a = new Audio(url);
      audio.current = a;
      a.onended = () => audio.current === a && setPlaying(null);
      setLoading(null);
      setPlaying(v.id);
      await a.play();
    } catch (e) {
      if (t !== token.current) return;
      setPlaying(null);
      setLoading(null);
      setError(`Couldn't play ${v.name}: ${(e as Error).message}`);
    }
  }

  return { playing, loading, error, toggle, stop };
}

/** "Choose your agent's voice": a few voices to preview and pick right here, plus the full library. */
export function VoiceCards({
  voices,
  value,
  language,
  onChange,
  pinned,
}: {
  voices: VoicesResponse | undefined;
  value: string;
  language: string;
  onChange: (id: string) => void;
  /** Voice ids to show right after the selected one. */
  pinned?: string[];
}) {
  const [libraryOpen, setLibraryOpen] = useState(false);
  // Voices in the library, counting a speaker with several tones or versions once (as the picker shows them).
  const libraryCount = useMemo(
    () =>
      new Set(
        [...(voices?.featured ?? []), ...(voices?.voices ?? [])].map((v) =>
          v.family ? `f:${v.family}` : v.id,
        ),
      ).size,
    [voices],
  );
  const { data: rates } = useSWR<{ premium_voice_surcharge: number }>(
    "/api/billing/rates",
    fetcher,
    { revalidateOnFocus: false },
  );
  const { playing, loading, error, toggle, stop } = usePreview(language);
  const picks = useMemo(
    () => suggestedVoices(voices, language, value, pinned),
    [voices, language, value, pinned],
  );
  const surcharge = rates?.premium_voice_surcharge ?? 0;
  const canPreview = voices?.source !== "fallback";

  if (!voices) {
    return (
      <div className="grid gap-2 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-[76px] animate-pulse rounded-xl bg-zinc-100"
          />
        ))}
      </div>
    );
  }

  return (
    <div>
      <div
        role="radiogroup"
        aria-label="Voice"
        className="grid gap-2 sm:grid-cols-2"
      >
        {picks.map((v) => {
          const selected = v.id === value;
          const premium = v.category === "premium";
          const meta = [
            v.gender ? capitalize(v.gender) : null,
            v.accent
              ? capitalize(v.accent)
              : v.language
                ? languageName(v.language)
                : null,
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <div
              key={v.id}
              className={cn(
                "flex items-center gap-3 rounded-xl border bg-white p-3 transition",
                styles.suggestedCard,
                selected
                  ? "border-brand-500 ring-2 ring-brand-500/20"
                  : "border-zinc-200 hover:border-zinc-300",
              )}
            >
              <button
                type="button"
                onClick={() => void toggle(v)}
                disabled={!canPreview}
                aria-label={
                  playing === v.id ? `Stop ${v.name}` : `Play ${v.name}`
                }
                className={cn(
                  "relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full transition active:scale-95 disabled:opacity-40",
                  styles.avatarPreview,
                )}
              >
                <VoiceAvatar voice={v} animated className="h-12 w-12" />
                <span className={styles.avatarPlayBadge}>
                  {loading === v.id ? (
                    <Loader2 className="h-2.5 w-2.5 animate-spin" />
                  ) : playing === v.id ? (
                    <Pause className="h-2.5 w-2.5" />
                  ) : (
                    <Play className="h-2.5 w-2.5" />
                  )}
                </span>
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => onChange(v.id)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-2 focus-visible:outline-brand-500"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-col items-start gap-1">
                    <span
                      className={cn(
                        "text-sm font-semibold text-zinc-900",
                        styles.suggestedName,
                      )}
                    >
                      {v.name}
                    </span>
                    <Badge
                      tone={premium ? "violet" : "gray"}
                      className="shrink-0 text-[10px]"
                    >
                      {premium ? "Premium" : "Standard"}
                    </Badge>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-zinc-500">
                    {meta || "Voice"}
                    {premium && surcharge > 0
                      ? ` · +${surcharge} credits/min`
                      : ""}
                  </span>
                </span>
                <span
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                    selected
                      ? "border-brand-600 bg-brand-600 text-white"
                      : "border-zinc-300",
                  )}
                >
                  {selected && <Check className="h-3 w-3" strokeWidth={3} />}
                </span>
              </button>
            </div>
          );
        })}
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      <p className="mt-3 text-xs text-zinc-500">
        {picks.length
          ? `Suggested for ${languageName(language)} calls. You can change it any time.`
          : "No voices for this language yet."}
      </p>
      <button
        type="button"
        onClick={() => {
          stop();
          setLibraryOpen(true);
        }}
        className="group mt-3 flex w-full items-center gap-3 rounded-2xl border-2 border-dashed border-brand-300 bg-brand-50/60 px-4 py-3.5 text-left transition hover:border-brand-500 hover:bg-brand-50"
      >
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-600 text-white shadow-md shadow-brand-600/25">
          <Library className="h-5 w-5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-zinc-900">
            Explore the full voice library
          </span>
          <span className="block text-xs text-zinc-600">
            {libraryCount > 4 ? `${libraryCount} voices` : "More voices"} —
            accents, tones and premium cloned voices
          </span>
        </span>
        <ChevronRight className="h-5 w-5 shrink-0 text-brand-600 transition group-hover:translate-x-0.5" />
      </button>

      <Modal
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        title="Voice library"
        wide
      >
        <VoicePicker
          voices={voices.voices ?? []}
          featured={voices.featured ?? []}
          loading={false}
          source={voices.source}
          value={value}
          speed={1}
          language={language}
          onChange={(id) => onChange(id)}
          inline
        />
        <div className="mt-4 flex justify-end">
          <Button variant="primary" onClick={() => setLibraryOpen(false)}>
            Use this voice
          </Button>
        </div>
      </Modal>
    </div>
  );
}
