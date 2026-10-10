"use client";

import { Check, Loader2, Play, Search, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Voice } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Input, Select } from "../ui";

const PREVIEW_LINE = "Hey there, this is a quick preview of how I'll sound on your calls. Does this work for you?";

export function VoicePicker({
  voices,
  featured = [],
  source,
  value,
  speed,
  language,
  onChange,
}: {
  voices: Voice[];
  featured?: Voice[];
  source: string | undefined;
  value: string;
  speed: number;
  language: string;
  onChange: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [gender, setGender] = useState("");
  const [lang, setLang] = useState(language === "multi" ? "" : language);
  const [playing, setPlaying] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const isFeatured = featured.some((f) => f.id === value);
  const [showLibrary, setShowLibrary] = useState(false);
  const libraryOpen = showLibrary || (!isFeatured && !!value && featured.length > 0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const selectedRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => () => audio.current?.pause(), []);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, []);

  const languages = useMemo(() => [...new Set(voices.map((v) => v.language).filter(Boolean))].sort() as string[], [voices]);
  const genders = useMemo(() => [...new Set(voices.map((v) => v.gender).filter(Boolean))].sort() as string[], [voices]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return voices.filter(
      (v) =>
        (!gender || v.gender === gender) &&
        (!lang || v.language === lang || v.id === value) &&
        (!needle || `${v.name} ${v.description ?? ""}`.toLowerCase().includes(needle)),
    );
  }, [voices, q, gender, lang, value]);

  async function preview(id: string) {
    setError("");
    if (playing === id) {
      audio.current?.pause();
      setPlaying(null);
      return;
    }
    audio.current?.pause();
    setLoading(id);
    try {
      const res = await fetch("/api/settings/voices/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice_id: id, text: PREVIEW_LINE, speed, language }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Preview failed");
      const url = URL.createObjectURL(await res.blob());
      const a = new Audio(url);
      audio.current = a;
      a.onended = () => {
        setPlaying(null);
        URL.revokeObjectURL(url);
      };
      await a.play();
      setPlaying(id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(null);
    }
  }

  const playButton = (id: string, name: string) => (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        preview(id);
      }}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-600 hover:border-brand-500 hover:text-brand-600"
      aria-label={`Preview ${name}`}
    >
      {loading === id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : playing === id ? <Square className="h-3 w-3" /> : <Play className="h-3.5 w-3.5" />}
    </button>
  );

  return (
    <div className="space-y-3">
      {featured.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {featured.map((v) => {
            const selected = v.id === value;
            return (
              <div
                key={v.id}
                role="button"
                tabIndex={0}
                onClick={() => onChange(v.id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onChange(v.id)}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition",
                  selected ? "border-brand-500 bg-brand-50 ring-2 ring-brand-100" : "border-zinc-200 hover:border-zinc-300",
                )}
              >
                {playButton(v.id, v.name)}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {v.name}
                    {v.gender && <span className="text-[11px] font-normal text-zinc-500">{v.gender}</span>}
                  </div>
                  <div className="line-clamp-2 text-xs text-zinc-500">{v.description}</div>
                </div>
                {selected && <Check className="h-4 w-4 shrink-0 text-brand-600" />}
              </div>
            );
          })}
        </div>
      )}
      {error && featured.length > 0 && !libraryOpen && <p className="text-xs text-red-600">{error}</p>}
      {featured.length > 0 && (
        <button type="button" onClick={() => setShowLibrary((v) => !v)} className="text-xs font-medium text-brand-600 hover:text-brand-700">
          {libraryOpen ? "Hide full voice library" : `Browse all ${voices.length} voices…`}
        </button>
      )}
      {(libraryOpen || featured.length === 0) && (
    <div className="rounded-xl border border-zinc-200">
      <div className="flex flex-wrap gap-2 border-b border-zinc-100 p-3">
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${voices.length} voices…`} className="pl-9" />
        </div>
        <Select className="w-auto" value={gender} onChange={(e) => setGender(e.target.value)} aria-label="Gender">
          <option value="">Any gender</option>
          {genders.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </Select>
        <Select className="w-auto" value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Language">
          <option value="">Any language</option>
          {languages.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </Select>
      </div>
      <div className="scroll-thin max-h-80 overflow-y-auto">
        {filtered.length === 0 && <p className="p-4 text-sm text-zinc-500">No voices match.</p>}
        {filtered.slice(0, 200).map((v) => {
          const selected = v.id === value;
          return (
            <div key={v.id} className={cn("flex items-center gap-3 border-b border-zinc-50 px-3 py-2", selected && "bg-brand-50")}>
              {playButton(v.id, v.name)}
              <button type="button" ref={selected ? selectedRef : undefined} onClick={() => onChange(v.id)} className="min-w-0 flex-1 text-left">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <span className="truncate">{v.name}</span>
                  {v.mine && <span className="rounded bg-violet-50 px-1.5 text-[10px] font-medium text-violet-700">Your clone</span>}
                </div>
                <div className="truncate text-xs text-zinc-500">
                  {[v.gender, v.language, v.description].filter(Boolean).join(" · ")}
                </div>
              </button>
              {selected && <Check className="h-4 w-4 shrink-0 text-brand-600" />}
            </div>
          );
        })}
        {filtered.length > 200 && <p className="p-3 text-center text-xs text-zinc-400">Showing 200 of {filtered.length}. Search to narrow it down.</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 px-3 py-2">
        <span className="text-xs text-zinc-500">Or paste a voice ID:</span>
        <Input value={value} onChange={(e) => onChange(e.target.value.trim())} className="h-8 min-w-0 flex-1 font-mono text-xs" aria-label="Voice ID" />
      </div>
      <div className="border-t border-zinc-100 px-3 py-2 text-xs text-zinc-500">
        {error ? (
          <span className="text-red-600">{error}</span>
        ) : source === "fallback" ? (
          "Add CARTESIA_API_KEY to browse and preview the full voice library."
        ) : (
          "▶ plays a sample at the current speed. Clone your own voice at play.cartesia.ai and it shows up here."
        )}
      </div>
    </div>
      )}
    </div>
  );
}
