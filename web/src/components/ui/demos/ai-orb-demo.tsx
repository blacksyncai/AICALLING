"use client";
import { Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AI_ORB_LABELS, AI_ORB_STATES, AiOrb, type AiOrbState } from "../ai-orb";
const settings = { showGallery: true, stepMs: 1600 };
const TURN: AiOrbState[] = ["listening", "thinking", "tool-call", "tool-result", "reasoning", "streaming", "done"];
/** Scripted design demo only; production panels use real activity signals. */
export default function Demo(props: Partial<typeof settings>) {
  const s = { ...settings, ...props };
  const [state, setState] = useState<AiOrbState>("idle");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const clear = useCallback(() => { for (const timer of timers.current) clearTimeout(timer); timers.current = []; }, []);
  useEffect(() => clear, [clear]);
  const play = () => { clear(); TURN.forEach((next, index) => timers.current.push(setTimeout(() => setState(next), index * s.stepMs))); };
  const reset = () => { clear(); setState("idle"); };
  return <div className="flex min-h-[560px] w-full items-center justify-center bg-zinc-50 px-6 pb-6 pt-16 text-zinc-900">
    <div className="flex w-full max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-4 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
        <div className="flex min-w-0 flex-1 basis-56 items-center gap-5"><AiOrb decorative size="lg" state={state} />
          <div className="min-w-0 flex-1"><p className="text-sm font-medium">Operations assistant</p><p aria-live="polite" className="text-sm text-zinc-500">{AI_ORB_LABELS[state]}<span className="ml-2 inline-block whitespace-nowrap rounded-full border border-zinc-200 px-2 py-0.5 font-mono text-xs">{state}</span></p></div>
        </div>
        <div className="flex shrink-0 items-center gap-2"><button className="inline-flex h-9 items-center gap-2 rounded-full bg-brand-600 px-4 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-brand-500" onClick={play} type="button"><Play aria-hidden className="size-4" />Run a turn</button><button aria-label="Reset to idle" className="inline-flex size-9 items-center justify-center rounded-full border border-zinc-200 text-zinc-500 focus-visible:outline-2 focus-visible:outline-brand-500" onClick={reset} type="button"><RotateCcw aria-hidden className="size-4" /></button></div>
      </div>
      {s.showGallery ? <ul className="grid grid-cols-2 gap-3 sm:grid-cols-5">{AI_ORB_STATES.map(item => <li className="flex flex-col items-center gap-2 rounded-xl border border-zinc-200 bg-white px-2 py-4" key={item}><AiOrb settleMs={60_000} size="lg" state={item} /><span className="font-mono text-xs text-zinc-500">{item}</span></li>)}</ul> : null}
    </div>
  </div>;
}
