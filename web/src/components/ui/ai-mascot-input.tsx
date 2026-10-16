"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowUp, LoaderCircle, Mic, Square } from "lucide-react";

export type RobotEmotion = "reading" | "thinking";
export interface ChatSubmitData { prompt: string }
export interface AiMascotInputProps {
  onSubmit: (data: ChatSubmitData) => void | Promise<void>;
  isProcessing?: boolean;
  value?: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  title?: string;
  subtitle?: string;
  showWelcome?: boolean;
  enableVoice?: boolean;
  className?: string;
  containerClassName?: string;
}
interface Recognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  abort: () => void;
}
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};

export function RobotBeta({ emotion, textLength = 0, isListening = false }: {
  emotion: RobotEmotion; textLength?: number; isListening?: boolean;
}) {
  const reduced = useReducedMotion();
  const thinking = emotion === "thinking";
  const color = isListening ? "#f3663b" : thinking ? "#fbbf24" : "#34d399";
  return (
    <motion.div aria-hidden="true" className="relative mx-auto flex h-24 w-28 items-center justify-center select-none"
      animate={{ y: reduced ? 0 : thinking ? [0, -4, 0] : [0, -2, 0] }}
      transition={{ duration: 2.2, repeat: reduced ? 0 : Infinity }}>
      <div className="absolute top-3 left-6 h-4 w-3 rounded-tl-xl border border-zinc-300 bg-zinc-200 dark:border-zinc-600 dark:bg-zinc-700" />
      <div className="absolute top-3 right-6 h-4 w-3 rounded-tr-xl border border-zinc-300 bg-zinc-200 dark:border-zinc-600 dark:bg-zinc-700" />
      {[-1, 1].map(side => <span key={side} className="absolute h-6 w-1 rounded-full" style={{ [side === -1 ? "left" : "right"]: 8, background: color, boxShadow: `0 0 9px ${color}` }} />)}
      <div className="relative z-10 h-16 w-24 rounded-2xl border-2 border-zinc-300 bg-zinc-100 p-1.5 shadow-md dark:border-zinc-600 dark:bg-zinc-800">
        <div className="relative flex h-full items-center justify-center gap-4 overflow-hidden rounded-xl bg-[#050b09] shadow-inner">
          {[0, 1].map(i => <motion.span key={i} className="h-5 w-2.5 rounded-sm" style={{ background: color, boxShadow: `0 0 10px ${color}` }}
            animate={reduced ? { x: 0, scaleY: 1 } : thinking ? { y: [0, -3, 0] } : { x: Math.sin(textLength * .25) * 5, scaleY: [1, 1, .12, 1] }}
            transition={thinking ? { duration: 1.1, repeat: reduced ? 0 : Infinity } : { x: { type: "spring", stiffness: 260, damping: 25 }, scaleY: { duration: 4.5, times: [0, .92, .95, 1], repeat: reduced ? 0 : Infinity } }} />)}
          <div className="pointer-events-none absolute inset-0" style={{ backgroundImage: "repeating-linear-gradient(transparent 0 2px,rgba(0,0,0,.55) 2px 4px)" }} />
        </div>
      </div>
    </motion.div>
  );
}

/** Radar's real draft composer. Model/search/file controls require corresponding backend support. */
export function AiMascotInput({ onSubmit, isProcessing = false, value, onChange, disabled = false,
  placeholder = "Describe the workflow you want to build…", title = "What should Radar build?",
  subtitle = "Describe your idea. Review the workflow before it runs.", showWelcome = true,
  enableVoice = true, className = "", containerClassName = "" }: AiMascotInputProps) {
  const [internalValue, setInternalValue] = useState("");
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [error, setError] = useState("");
  const recognition = useRef<Recognition | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const locked = useRef(false);
  const reduced = useReducedMotion();
  const text = value ?? internalValue;
  const busy = isProcessing || sending;
  const active = !!text || listening || busy;
  const change = (next: string) => { if (value === undefined) setInternalValue(next); onChange?.(next); };
  const stop = () => { const old = recognition.current; recognition.current = null; if (old) { old.onresult = null; old.onend = null; old.onerror = null; old.abort(); } setListening(false); };
  useEffect(() => {
    const w = window as SpeechWindow;
    setVoiceSupported(!!(w.SpeechRecognition || w.webkitSpeechRecognition));
    return () => { const old = recognition.current; if (old) { old.onresult = null; old.onend = null; old.onerror = null; old.abort(); } };
  }, []);
  useEffect(() => { if (disabled || isProcessing) stop(); }, [disabled, isProcessing]);
  useEffect(() => { if (textarea.current) { textarea.current.style.height = "auto"; textarea.current.style.height = `${Math.min(240, Math.max(68, textarea.current.scrollHeight))}px`; } }, [text]);
  const dictate = () => {
    if (listening) { stop(); return; }
    const w = window as SpeechWindow;
    const Speech = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!Speech || disabled || busy) return;
    setError("");
    const instance = new Speech();
    const base = text.trim() ? `${text.trim()} ` : "";
    instance.continuous = false;
    instance.interimResults = true;
    instance.lang = navigator.language || "en-US";
    instance.onresult = event => {
      if (recognition.current !== instance) return;
      change((base + Array.from(event.results, item => item[0]?.transcript ?? "").join(" ")).slice(0, 4000));
    };
    instance.onerror = event => { setError(event.error === "not-allowed" ? "Microphone access was denied. Allow it in your browser or type your request." : "Voice input stopped. Try again or type your request."); stop(); };
    instance.onend = () => { if (recognition.current === instance) { recognition.current = null; setListening(false); } };
    recognition.current = instance;
    try { instance.start(); setListening(true); } catch { setError("Voice input could not start. Type your request instead."); stop(); }
  };
  const submit = async () => {
    if (disabled || busy || locked.current || !text.trim()) return;
    locked.current = true; stop(); setError(""); setSending(true);
    try { await onSubmit({ prompt: text.trim() }); if (value === undefined) setInternalValue(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not send your request. Try again."); }
    finally { locked.current = false; setSending(false); }
  };
  return <div className={`min-w-0 w-full ${containerClassName}`}>
    <AnimatePresence initial={false}>
      {showWelcome && !active && <motion.div key="welcome" className="mb-5 text-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : .15 }}>
        <RobotBeta emotion="reading" />
        <h3 className="mt-2 text-xl font-semibold tracking-tight text-zinc-950 dark:text-white">{title}</h3>
        <p className="mt-1 text-xs leading-6 text-zinc-500 dark:text-zinc-400">{subtitle}</p>
      </motion.div>}
    </AnimatePresence>
    {active && <div className="ml-auto h-24 w-28 mr-3"><RobotBeta emotion={busy ? "thinking" : "reading"} textLength={text.length} isListening={listening} /></div>}
    <div className={`min-w-0 rounded-3xl border border-zinc-200 bg-white p-4 shadow-[0_12px_35px_#211b1808] focus-within:border-brand-400 dark:border-zinc-700 dark:bg-zinc-900 ${className}`}>
      <textarea ref={textarea} aria-label="Describe your automation" value={text} maxLength={4000} rows={3} disabled={disabled || busy}
        onChange={e => change(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void submit(); } }}
        placeholder={listening ? "Listening…" : placeholder}
        className="block w-full resize-none bg-transparent text-sm leading-6 text-zinc-900 outline-none placeholder:text-zinc-400 dark:text-zinc-100" />
      <div className="mt-3 flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-zinc-100 pt-3 dark:border-zinc-800">
        <span className="text-[11px] text-zinc-500">{busy ? "Drafting your workflow…" : "Draft mode · Review before activation"}</span>
        <div className="flex shrink-0 items-center gap-2">
          {enableVoice && <button type="button" aria-label={listening ? "Stop voice input" : "Dictate with voice"} aria-pressed={listening} disabled={disabled || busy || !voiceSupported}
            title={voiceSupported ? "Your browser processes dictation using its speech service" : "Voice input is unavailable in this browser"} onClick={dictate}
            className={`flex h-10 w-10 items-center justify-center rounded-full disabled:opacity-35 ${listening ? "bg-orange-100 text-brand-600" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}>
            {listening ? <Square size={16} /> : <Mic size={17} />}
          </button>}
          <button type="button" aria-label="Draft workflow" disabled={disabled || busy || !text.trim()} onClick={() => void submit()}
            className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-600 text-white transition-colors hover:bg-brand-700 disabled:bg-zinc-100 disabled:text-zinc-400 dark:disabled:bg-zinc-800">
            {busy ? <LoaderCircle size={17} className="motion-safe:animate-spin" /> : <ArrowUp size={18} />}
          </button>
        </div>
      </div>
    </div>
    <p className="mt-3 px-1 text-[11px] leading-5 text-zinc-500" aria-live="polite">{listening ? "Listening. Stop dictation to finish editing." : "Drafting does not move contacts or place calls."}</p>
    {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
  </div>;
}
export default AiMascotInput;
