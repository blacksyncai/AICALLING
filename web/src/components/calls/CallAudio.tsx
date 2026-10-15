"use client";

import { Loader2, Pause, Play, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useToast } from "@/components/toast";
import { fetcher } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DownloadRecording } from "./DownloadRecording";

type Track = { id: string; label: string };
type Ctx = { current: Track | null; playing: boolean; loading: string | null; toggle: (t: Track) => void };
const AudioCtx = createContext<Ctx | null>(null);

const clock = (s: number) => (Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00");

/** One shared player for a list of calls: ▶ on a row plays it out loud, and a small bar lets you scrub or stop. */
export function CallAudioProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const audio = useRef<HTMLAudioElement | null>(null);
  const [current, setCurrent] = useState<Track | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState<string | null>(null);
  const [time, setTime] = useState({ at: 0, len: 0 });

  useEffect(() => {
    const a = new Audio();
    audio.current = a;
    const sync = () => setTime({ at: a.currentTime, len: a.duration });
    a.addEventListener("timeupdate", sync);
    a.addEventListener("loadedmetadata", sync);
    a.addEventListener("play", () => setPlaying(true));
    a.addEventListener("pause", () => setPlaying(false));
    a.addEventListener("ended", () => setPlaying(false));
    return () => {
      a.pause();
      a.src = "";
    };
  }, []);

  const toggle = useCallback(
    async (t: Track) => {
      const a = audio.current;
      if (!a) return;
      if (current?.id === t.id && a.src) {
        if (a.paused) void a.play();
        else a.pause();
        return;
      }
      setLoading(t.id);
      try {
        const r = await fetcher<{ status: string; url: string | null }>(`/api/calls/${t.id}/recording`);
        if (!r.url) {
          toast(r.status === "processing" ? "The recording is still processing — try again in a minute." : "No recording for this call.", "error");
          return;
        }
        a.pause();
        a.src = r.url;
        setCurrent(t);
        setTime({ at: 0, len: 0 });
        await a.play();
      } catch (e) {
        toast((e as Error).message || "Couldn't play the recording.", "error");
      } finally {
        setLoading(null);
      }
    },
    [current, toast],
  );

  function stop() {
    const a = audio.current;
    if (a) {
      a.pause();
      a.src = "";
    }
    setCurrent(null);
  }

  return (
    <AudioCtx.Provider value={{ current, playing, loading, toggle }}>
      {children}
      {current && (
        <div className="fixed bottom-5 left-1/2 z-40 flex w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 items-center gap-3 rounded-2xl bg-zinc-900 px-4 py-3 text-white shadow-2xl">
          <button
            type="button"
            onClick={() => void toggle(current)}
            aria-label={playing ? "Pause" : "Play"}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-600 hover:bg-brand-500"
          >
            {playing ? <Pause className="h-4 w-4" /> : <Play className="ml-0.5 h-4 w-4" />}
          </button>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{current.label}</div>
            <div className="mt-1 flex items-center gap-2 text-[11px] tabular-nums text-zinc-400">
              <span>{clock(time.at)}</span>
              <input
                type="range"
                min={0}
                max={Number.isFinite(time.len) && time.len > 0 ? time.len : 0}
                step={0.1}
                value={time.at}
                onChange={(e) => {
                  if (audio.current) audio.current.currentTime = Number(e.target.value);
                }}
                aria-label="Seek"
                className="h-1 flex-1 accent-brand-500"
              />
              <span>{clock(time.len)}</span>
            </div>
          </div>
          <DownloadRecording callId={current.id} label="MP3" className="rounded-md px-1.5 py-1 text-zinc-300 hover:bg-white/10 hover:text-white" />
          <button type="button" onClick={stop} aria-label="Stop" className="rounded-md p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </AudioCtx.Provider>
  );
}

/** ▶ / ❚❚ for one call's recording (plays through the shared player). */
export function PlayButton({ id, label, className }: { id: string; label: string; className?: string }) {
  const ctx = useContext(AudioCtx);
  if (!ctx) return null;
  const mine = ctx.current?.id === id;
  const busy = ctx.loading === id;
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        void ctx.toggle({ id, label });
      }}
      title={mine && ctx.playing ? "Pause" : "Play recording"}
      aria-label={mine && ctx.playing ? "Pause recording" : "Play recording"}
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded-lg transition",
        mine && ctx.playing ? "bg-brand-600 text-white" : "text-brand-600 hover:bg-brand-50",
        className,
      )}
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : mine && ctx.playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
    </button>
  );
}
