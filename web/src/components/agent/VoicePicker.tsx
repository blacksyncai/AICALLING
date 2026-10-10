"use client";

import { AlertTriangle, Check, ChevronDown, Loader2, Play, Search, Square, X } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { Voice, VoiceCategory } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button, Input, Select } from "../ui";
import { capitalize, languageMismatch, languageName, listKeyHandler, usePopover } from "./picker-utils";

const PREVIEW_LINE = "Hey there, this is a quick preview of how I'll sound on your calls. Does this work for you?";
const MAX_ROWS = 200;
const DEFAULT_LABELS: Record<Cat, string> = { premium: "Premium Human Voices", standard: "Standard AI Voices" };

type Cat = "premium" | "standard";

function voiceMeta(v: Voice) {
  return [v.gender && capitalize(v.gender), v.accent, languageName(v.language)].filter(Boolean).join(" · ");
}

/**
 * Compact voice selector: a trigger showing the chosen voice that opens a searchable,
 * keyboard-accessible listbox split into Premium / Standard tabs, with one-at-a-time previews.
 *
 * Props are backward compatible with the old card picker (used by the AI builder).
 */
export function VoicePicker({
  voices,
  featured = [],
  loading: listLoading = false,
  source,
  value,
  speed,
  language,
  onChange,
  agentLanguage,
  categories,
  message,
}: {
  voices: Voice[];
  featured?: Voice[];
  loading?: boolean;
  source: string | undefined;
  value: string;
  speed: number;
  /** Language previews are spoken in (the agent's language). */
  language: string;
  onChange: (id: string) => void;
  /** Agent language to check the voice against; defaults to `language`. */
  agentLanguage?: string;
  categories?: VoiceCategory[];
  /** Catalog notice from the API (e.g. why the fallback list is shown). */
  message?: string | null;
}) {
  const uid = useId();
  const { open, setOpen, close, rootRef, triggerRef } = usePopover<HTMLButtonElement>();
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const featuredIds = useMemo(() => new Set(featured.map((f) => f.id)), [featured]);
  const catOf = useCallback(
    (v: Voice): Cat => v.category ?? (featuredIds.has(v.id) || v.is_clone || v.mine ? "premium" : "standard"),
    [featuredIds],
  );

  // Featured voices missing from the list (older API) are merged in so they stay pickable.
  const all = useMemo(() => {
    const ids = new Set(voices.map((v) => v.id));
    return [...featured.filter((f) => !ids.has(f.id)), ...voices];
  }, [voices, featured]);
  const selected = all.find((v) => v.id === value);
  const labels: Record<Cat, string> = {
    premium: categories?.find((c) => c.key === "premium")?.label ?? DEFAULT_LABELS.premium,
    standard: categories?.find((c) => c.key === "standard")?.label ?? DEFAULT_LABELS.standard,
  };
  const counts: Record<Cat, number> = {
    premium: all.filter((v) => catOf(v) === "premium").length,
    standard: all.filter((v) => catOf(v) === "standard").length,
  };

  const [tab, setTab] = useState<Cat>("premium");
  const [q, setQ] = useState("");
  const [lang, setLang] = useState("");
  const [accent, setAccent] = useState("");
  const [active, setActive] = useState(-1);
  const [pasting, setPasting] = useState(false);
  const [pasted, setPasted] = useState("");

  // Preview state: one clip at a time, object URLs cached per (voice, speed, language).
  const [playing, setPlaying] = useState<string | null>(null);
  const [fetching, setFetching] = useState<string | null>(null);
  const [error, setError] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const clipCache = useRef(new Map<string, string>());
  const playToken = useRef(0);

  const stop = useCallback(() => {
    playToken.current++;
    audio.current?.pause();
    audio.current = null;
    setPlaying(null);
    setFetching(null);
  }, []);

  useEffect(() => {
    const cache = clipCache.current;
    return () => {
      audio.current?.pause();
      cache.forEach((url) => URL.revokeObjectURL(url));
      cache.clear();
    };
  }, []);

  function openPicker() {
    const cat = selected ? catOf(selected) : counts.premium ? "premium" : "standard";
    setTab(cat === "premium" && !counts.premium ? "standard" : cat);
    setQ("");
    setAccent("");
    setError("");
    setPasting(false);
    setOpen(true);
    requestAnimationFrame(() => searchRef.current?.focus());
  }

  useEffect(() => {
    if (!open) stop();
  }, [open, stop]);

  const canPreview = (v: Voice) => v.preview ?? source !== "fallback";

  async function togglePreview(v: Voice) {
    setError("");
    if (playing === v.id || fetching === v.id) {
      stop();
      return;
    }
    stop();
    const token = playToken.current;
    const key = `${v.id}|${speed}|${language}`;
    try {
      let url = clipCache.current.get(key);
      if (!url) {
        setFetching(v.id);
        const res = await fetch("/api/settings/voices/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voice_id: v.id, text: PREVIEW_LINE, speed, language }),
        });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Preview failed");
        url = URL.createObjectURL(await res.blob());
        clipCache.current.set(key, url);
      }
      if (token !== playToken.current) return; // another preview started meanwhile
      const a = new Audio(url);
      audio.current = a;
      a.onended = () => {
        if (audio.current === a) setPlaying(null);
      };
      setFetching(null);
      setPlaying(v.id);
      await a.play();
    } catch (e) {
      if (token !== playToken.current) return;
      setPlaying(null);
      setFetching(null);
      setError(`Couldn't preview ${v.name}: ${(e as Error).message}`);
    }
  }

  // Filters are built from the voices in the current tab.
  const inTab = useMemo(() => all.filter((v) => catOf(v) === tab), [all, tab, catOf]);
  const languages = useMemo(
    () => [...new Set(inTab.map((v) => v.language).filter(Boolean) as string[])].sort((a, b) => languageName(a).localeCompare(languageName(b))),
    [inTab],
  );
  const accents = useMemo(
    () => [...new Set(inTab.filter((v) => !lang || v.language === lang).map((v) => v.accent).filter(Boolean) as string[])].sort(),
    [inTab, lang],
  );
  const effLang = languages.includes(lang) ? lang : "";
  const effAccent = accents.includes(accent) ? accent : "";

  const matches = useCallback(
    (v: Voice) => {
      const needle = q.trim().toLowerCase();
      return (
        (!effLang || v.language === effLang) &&
        (!effAccent || v.accent === effAccent) &&
        (!needle || `${v.name} ${v.description ?? ""} ${v.accent ?? ""}`.toLowerCase().includes(needle))
      );
    },
    [q, effLang, effAccent],
  );
  const filtered = useMemo(() => inTab.filter(matches), [inTab, matches]);
  const shown = filtered.slice(0, MAX_ROWS);
  const otherTab: Cat = tab === "premium" ? "standard" : "premium";
  const otherMatches = useMemo(
    () => (q.trim() ? all.filter((v) => catOf(v) === otherTab && matches(v)).length : 0),
    [all, catOf, otherTab, matches, q],
  );

  // Keep the active row on the selected voice (or first row) as the list changes.
  useEffect(() => {
    if (!open) return;
    const i = shown.findIndex((v) => v.id === value);
    setActive(i >= 0 ? i : shown.length ? 0 : -1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab, q, effLang, effAccent, shown.length]);

  useEffect(() => {
    if (active < 0) return;
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  function choose(id: string) {
    onChange(id);
    close();
  }

  const onKeyDown = listKeyHandler(shown.length, active, setActive, (i) => choose(shown[i].id));
  const optionId = (i: number) => `${uid}-opt-${i}`;
  const mismatch = selected && languageMismatch(selected.language, agentLanguage ?? language);

  const triggerLabel = selected ? (
    <>
      <span className="font-medium text-zinc-900">{selected.name}</span>
      <span className="text-zinc-500">
        {" — "}
        {[catOf(selected) === "premium" ? "Premium" : "Standard", languageName(selected.language), selected.gender && capitalize(selected.gender)]
          .filter(Boolean)
          .join(" · ")}
      </span>
    </>
  ) : value ? (
    <>
      <span className="font-medium text-zinc-900">Custom voice</span>
      <span className="font-mono text-xs text-zinc-500"> · {value}</span>
    </>
  ) : (
    <span className="text-zinc-500">Choose a voice</span>
  );

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={listLoading}
        onClick={() => (open ? close() : openPicker())}
        onKeyDown={(e) => {
          if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !open) {
            e.preventDefault();
            openPicker();
          }
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={selected ? `Voice: ${selected.name}. Change voice` : value ? `Voice: custom ${value}. Change voice` : "Choose a voice"}
        className={cn(
          "flex min-h-11 w-full items-center gap-3 rounded-xl border bg-white px-3 py-2 text-left text-sm transition",
          "focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100",
          open ? "border-brand-500 ring-2 ring-brand-100" : "border-zinc-200 hover:border-zinc-300",
          listLoading && "cursor-wait opacity-70",
        )}
      >
        {listLoading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-zinc-400" />
            <span className="flex-1 text-zinc-500">Loading voices…</span>
          </>
        ) : (
          <>
            <Avatar name={selected?.name ?? (value ? "#" : "?")} premium={!!selected && catOf(selected) === "premium"} />
            <span className="min-w-0 flex-1 truncate">{triggerLabel}</span>
            <ChevronDown className={cn("h-4 w-4 shrink-0 text-zinc-400 transition", open && "rotate-180")} />
          </>
        )}
      </button>

      {mismatch && (
        <p className="mt-1.5 flex items-start gap-1.5 text-xs text-amber-700" role="status">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            This voice speaks {languageName(selected.language)}; your agent is set to {languageName(agentLanguage ?? language)} — pick a{" "}
            {languageName(agentLanguage ?? language)} voice or switch the agent language (or use Multilingual).
          </span>
        </p>
      )}
      {!open && error && <p className="mt-1.5 text-xs text-red-600">{error}</p>}

      {open && (
        <>
          <div className="fixed inset-0 z-40 bg-zinc-900/30 sm:hidden" aria-hidden onClick={() => close(false)} />
          <div
            role="dialog"
            aria-label="Choose a voice"
            className={cn(
              "fixed inset-x-0 bottom-0 z-50 flex max-h-[85vh] flex-col rounded-t-2xl border border-zinc-200 bg-white shadow-xl",
              "sm:absolute sm:inset-x-0 sm:bottom-auto sm:top-full sm:mt-2 sm:max-h-[min(32rem,70vh)] sm:rounded-xl",
            )}
          >
            <div className="flex items-center justify-between px-3 pt-3 sm:hidden">
              <span className="text-sm font-semibold">Choose a voice</span>
              <button type="button" onClick={() => close()} className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100" aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div role="tablist" aria-label="Voice category" className="flex gap-1 border-b border-zinc-100 px-3 pt-3">
              {(["premium", "standard"] as Cat[]).map((c) => (
                <button
                  key={c}
                  type="button"
                  role="tab"
                  aria-selected={tab === c}
                  onClick={() => {
                    setTab(c);
                    searchRef.current?.focus();
                  }}
                  className={cn(
                    "-mb-px flex-1 truncate border-b-2 px-2 pb-2 text-xs font-medium transition sm:flex-none sm:text-sm",
                    tab === c ? "border-brand-600 text-brand-700" : "border-transparent text-zinc-500 hover:text-zinc-800",
                  )}
                >
                  {labels[c]} <span className="text-zinc-400">({counts[c]})</span>
                </button>
              ))}
            </div>

            <div className="flex flex-wrap gap-2 border-b border-zinc-100 p-3">
              <div className="relative min-w-[160px] flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                <Input
                  ref={searchRef}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="Search voices by name…"
                  className="pl-9"
                  role="combobox"
                  aria-expanded
                  aria-controls={`${uid}-list`}
                  aria-activedescendant={active >= 0 ? optionId(active) : undefined}
                  aria-autocomplete="list"
                  aria-label="Search voices"
                />
              </div>
              {languages.length > 1 && (
                <Select className="w-auto max-w-[45%]" value={effLang} onChange={(e) => setLang(e.target.value)} aria-label="Filter by language">
                  <option value="">All languages</option>
                  {languages.map((l) => (
                    <option key={l} value={l}>
                      {languageName(l)}
                    </option>
                  ))}
                </Select>
              )}
              {accents.length > 0 && (
                <Select className="w-auto max-w-[45%]" value={effAccent} onChange={(e) => setAccent(e.target.value)} aria-label="Filter by accent">
                  <option value="">All accents</option>
                  {accents.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </Select>
              )}
            </div>

            <ul ref={listRef} id={`${uid}-list`} role="listbox" aria-label={labels[tab]} className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1">
              {shown.length === 0 && (
                <li role="presentation" className="px-4 py-6 text-center text-sm text-zinc-500">
                  No voices match{q.trim() ? ` “${q.trim()}”` : ""}
                  {effLang ? ` in ${languageName(effLang)}` : ""}.
                  <div className="mt-2 flex flex-wrap justify-center gap-3 text-xs">
                    {(effLang || effAccent) && (
                      <button type="button" className="font-medium text-brand-600 hover:text-brand-700" onClick={() => (setLang(""), setAccent(""))}>
                        Clear filters
                      </button>
                    )}
                    {otherMatches > 0 && (
                      <button type="button" className="font-medium text-brand-600 hover:text-brand-700" onClick={() => setTab(otherTab)}>
                        {otherMatches} match{otherMatches === 1 ? "" : "es"} in {labels[otherTab]}
                      </button>
                    )}
                  </div>
                </li>
              )}
              {shown.map((v, i) => {
                const isSel = v.id === value;
                const previewable = canPreview(v);
                const meta = voiceMeta(v);
                return (
                  <li
                    key={v.id}
                    id={optionId(i)}
                    data-index={i}
                    role="option"
                    aria-selected={isSel}
                    onClick={() => choose(v.id)}
                    onMouseMove={() => active !== i && setActive(i)}
                    className={cn(
                      "flex cursor-pointer items-center gap-3 px-3 py-2",
                      i === active && "bg-zinc-50",
                      isSel && "bg-brand-50",
                    )}
                  >
                    <Avatar name={v.name} premium={catOf(v) === "premium"} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-sm font-medium text-zinc-900">
                        <span className="truncate">{v.name}</span>
                        {catOf(v) === "premium" && (
                          <span className="shrink-0 rounded bg-brand-50 px-1.5 text-[10px] font-semibold text-brand-700 ring-1 ring-brand-100">Premium</span>
                        )}
                        {(v.is_clone ?? v.mine) && (
                          <span className="shrink-0 rounded bg-violet-50 px-1.5 text-[10px] font-semibold text-violet-700">Clone</span>
                        )}
                      </div>
                      {(meta || v.description) && (
                        <div className="truncate text-xs text-zinc-500" title={v.description || undefined}>
                          {[meta, v.description].filter(Boolean).join(" · ")}
                        </div>
                      )}
                    </div>
                    <span title={previewable ? undefined : "Voice previews aren't available yet"}>
                      <button
                        type="button"
                        disabled={!previewable}
                        onClick={(e) => {
                          e.stopPropagation();
                          togglePreview(v);
                        }}
                        onKeyDown={(e) => e.stopPropagation()}
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-600 hover:border-brand-500 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-zinc-200 disabled:hover:text-zinc-600"
                        aria-label={playing === v.id ? `Stop preview of ${v.name}` : `Preview ${v.name}`}
                      >
                        {fetching === v.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : playing === v.id ? (
                          <Square className="h-3 w-3" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </span>
                    <Check className={cn("h-4 w-4 shrink-0 text-brand-600", !isSel && "invisible")} aria-hidden />
                  </li>
                );
              })}
              {filtered.length > MAX_ROWS && (
                <li role="presentation" className="p-3 text-center text-xs text-zinc-400">
                  Showing {MAX_ROWS} of {filtered.length}. Search to narrow it down.
                </li>
              )}
            </ul>

            <div className="space-y-2 border-t border-zinc-100 px-3 py-2 text-xs text-zinc-500">
              {error && (
                <p className="text-red-600" role="alert">
                  {error}
                </p>
              )}
              {(message || source === "fallback") && <p>{message ?? "The full voice library isn't available right now — showing a short list."}</p>}
              {pasting ? (
                <div className="flex items-center gap-2">
                  <Input
                    autoFocus
                    value={pasted}
                    onChange={(e) => setPasted(e.target.value)}
                    placeholder="BlackSync voice ID"
                    className="h-8 min-w-0 flex-1 font-mono text-xs"
                    aria-label="BlackSync voice ID"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        if (pasted.trim()) choose(pasted.trim());
                      }
                    }}
                  />
                  <Button type="button" size="sm" disabled={!pasted.trim()} onClick={() => choose(pasted.trim())}>
                    Use
                  </Button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setPasted(selected ? "" : value);
                    setPasting(true);
                  }}
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  Paste a BlackSync voice ID
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Avatar({ name, premium }: { name: string; premium?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
        premium ? "bg-brand-100 text-brand-700" : "bg-zinc-100 text-zinc-600",
      )}
    >
      {(name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}
