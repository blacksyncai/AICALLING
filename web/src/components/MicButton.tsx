"use client";

import { Loader2, Mic, Square } from "lucide-react";
import { forwardRef, useEffect, useRef, useState, type ComponentProps } from "react";
import { useToast } from "@/components/toast";
import { Input, Textarea } from "@/components/ui";
import { post } from "@/lib/api";
import { cn } from "@/lib/utils";

const MAX_SECONDS = 120;

type State = "idle" | "recording" | "working";

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
    if (MediaRecorder.isTypeSupported?.(t)) return t;
  }
  return "";
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(new Error("Couldn't read the recording."));
    r.readAsDataURL(blob);
  });
}

/** Append dictated text to an existing value with sensible spacing. */
export function appendDictation(current: string, text: string): string {
  const t = text.trim();
  if (!t) return current;
  if (!current.trim()) return t;
  return /\s$/.test(current) ? current + t : `${current} ${t}`;
}

/**
 * Talk instead of typing: click to record, click again to stop. The audio is transcribed on the server
 * (nothing is stored) and the text is handed to `onText`.
 */
export function MicButton({ onText, className, language }: { onText: (text: string) => void; className?: string; language?: string }) {
  const toast = useToast();
  const [state, setState] = useState<State>("idle");
  const [seconds, setSeconds] = useState(0);
  const [supported, setSupported] = useState(true);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => {
    setSupported(typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined");
    return () => {
      clearInterval(timer.current);
      stream.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function start() {
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      toast("Allow microphone access in your browser to talk instead of typing.", "error");
      return;
    }
    const mime = pickMime();
    const r = new MediaRecorder(stream.current, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    r.onstop = () => void finish(r.mimeType || mime || "audio/webm");
    rec.current = r;
    r.start();
    setSeconds(0);
    setState("recording");
    timer.current = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= MAX_SECONDS) stop();
        return s + 1;
      });
    }, 1000);
  }

  function stop() {
    clearInterval(timer.current);
    if (rec.current?.state === "recording") rec.current.stop();
    stream.current?.getTracks().forEach((t) => t.stop());
  }

  async function finish(mime: string) {
    setState("working");
    try {
      const blob = new Blob(chunks.current, { type: mime });
      const res = await post<{ text: string }>("/api/speech/transcribe", {
        audio_base64: await toBase64(blob),
        mime_type: mime,
        language: language && language !== "multi" ? language : undefined,
      });
      if (res.text) onText(res.text);
      else toast("We didn't catch anything. Try again a little closer to the mic.", "error");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setState("idle");
    }
  }

  if (!supported) return null;
  const label = state === "recording" ? "Stop recording" : state === "working" ? "Transcribing" : "Talk instead of typing";
  return (
    <button
      type="button"
      onClick={() => (state === "recording" ? stop() : state === "idle" ? void start() : undefined)}
      disabled={state === "working"}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-2 text-xs font-medium transition-colors",
        state === "recording" ? "bg-red-600 text-white hover:bg-red-700" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800",
        className,
      )}
    >
      {state === "working" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : state === "recording" ? (
        <>
          <Square className="h-3 w-3 fill-current" />
          <span className="tabular-nums">
            {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
          </span>
        </>
      ) : (
        <Mic className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

type TextareaProps = ComponentProps<typeof Textarea> & { value: string; onValue: (v: string) => void; language?: string };

/** Textarea with a mic button in its corner; dictated text is appended. */
export const VoiceTextarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function VoiceTextarea(
  { value, onValue, language, className, ...props },
  ref,
) {
  return (
    <div className="relative">
      <Textarea ref={ref} value={value} onChange={(e) => onValue(e.target.value)} className={cn("pb-9", className)} {...props} />
      <MicButton className="absolute bottom-2 right-4 bg-white/90" language={language} onText={(t) => onValue(appendDictation(value, t))} />
    </div>
  );
});

type InputProps = ComponentProps<typeof Input> & { value: string; onValue: (v: string) => void; language?: string };

/** Single-line input with a mic button inside the right edge. */
export function VoiceInput({ value, onValue, language, className, ...props }: InputProps) {
  return (
    <div className="relative min-w-0 flex-1">
      <Input value={value} onChange={(e) => onValue(e.target.value)} className={cn("pr-10", className)} {...props} />
      <MicButton className="absolute right-1 top-1/2 -translate-y-1/2" language={language} onText={(t) => onValue(appendDictation(value, t))} />
    </div>
  );
}
