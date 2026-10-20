"use client";

import { type ClassValue, clsx } from "clsx";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { type ComponentProps, type RefObject, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { twMerge } from "tailwind-merge";
import { type OrbState, ThinkingOrb } from "thinking-orbs";
import { AI_ORB_LABELS, type AiOrbState } from "./ai-orb-state";
export { AI_ORB_LABELS, AI_ORB_STATES, orbStateFor, type AiOrbState, type AgentActivity } from "./ai-orb-state";

function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
export type AiOrbTone = "muted" | "primary" | "attention" | "critical";
type OrbVisual = { orb: OrbState; tone: AiOrbTone; speed: number; paused: boolean; settles: boolean };
const CALM = 0.6;
const VISUALS: Record<AiOrbState, OrbVisual> = {
  done: { orb: "breathing", paused: false, settles: true, speed: CALM, tone: "primary" },
  error: { orb: "breathing", paused: true, settles: false, speed: 1, tone: "critical" },
  idle: { orb: "breathing", paused: false, settles: true, speed: CALM, tone: "muted" },
  listening: { orb: "listening", paused: false, settles: true, speed: 1, tone: "primary" },
  reasoning: { orb: "solving", paused: false, settles: false, speed: 1, tone: "primary" },
  streaming: { orb: "composing", paused: false, settles: false, speed: 1, tone: "primary" },
  thinking: { orb: "working", paused: false, settles: false, speed: 1, tone: "primary" },
  "tool-call": { orb: "searching", paused: false, settles: false, speed: 1, tone: "primary" },
  "tool-result": { orb: "connecting", paused: false, settles: false, speed: 1, tone: "primary" },
  "waiting-approval": { orb: "shaping", paused: false, settles: true, speed: 0.8, tone: "attention" },
};
const TONE_TOKENS: Record<AiOrbTone, readonly string[]> = {
  attention: ["--color-warning", "--color-chart-5", "--chart-5", "--color-amber-500"],
  critical: ["--color-destructive", "--destructive", "--color-red-600"],
  muted: ["--color-muted-foreground", "--muted-foreground", "--color-zinc-500"],
  primary: ["--color-primary", "--primary", "--color-brand-500"],
};

/** Include scoped theme containers as well as the root theme. */
function subscribeTheme(host: HTMLElement, onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  for (let node: HTMLElement | null = host; node; node = node.parentElement) {
    observer.observe(node, { attributeFilter: ["class", "style", "data-theme"], attributes: true });
  }
  const scheme = window.matchMedia("(prefers-color-scheme: dark)");
  scheme.addEventListener("change", onChange);
  return () => { observer.disconnect(); scheme.removeEventListener("change", onChange); };
}
let painter: CanvasRenderingContext2D | null | undefined;
function resolveTokens(tokens: readonly string[], host: HTMLElement): string | undefined {
  const probe = document.createElement("span");
  probe.style.display = "none";
  probe.style.color = tokens.reduceRight((fallback, token) => `var(${token}, ${fallback})`, "transparent");
  host.append(probe);
  const computed = getComputedStyle(probe).color;
  probe.remove();
  if (painter === undefined) {
    const canvas = document.createElement("canvas"); canvas.width = 1; canvas.height = 1;
    painter = canvas.getContext("2d", { willReadFrequently: true });
  }
  if (!(painter && computed)) return;
  painter.clearRect(0, 0, 1, 1); painter.fillStyle = "transparent"; painter.fillStyle = computed; painter.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = painter.getImageData(0, 0, 1, 1).data;
  if (!a) return;
  return `#${[r, g, b].map(channel => channel.toString(16).padStart(2, "0")).join("")}`;
}
function useOrbColor(host: RefObject<HTMLElement | null>, tone: AiOrbTone, override?: string): string | undefined {
  const [color, setColor] = useState<string>();
  const read = useCallback(() => {
    if (host.current) setColor(resolveTokens(override ? [override] : TONE_TOKENS[tone], host.current));
  }, [host, override, tone]);
  useEffect(() => { read(); if (host.current) return subscribeTheme(host.current, read); }, [host, read]);
  return color;
}
const noop = () => () => undefined;
const SIZE = { lg: { box: "size-16", dot: 1, px: 64 }, md: { box: "size-8", dot: 1.15, px: 32 }, sm: { box: "size-5", dot: 1.3, px: 20 } } as const;
export type AiOrbProps = Omit<ComponentProps<"span">, "aria-hidden" | "aria-label" | "children" | "role"> & {
  state: AiOrbState; size?: keyof typeof SIZE; label?: string; decorative?: boolean; colorToken?: string; settleMs?: number;
};
function useSettled(state: AiOrbState, settles: boolean, settleMs: number) {
  const [settledState, setSettledState] = useState<AiOrbState | null>(null);
  useEffect(() => {
    setSettledState(null);
    if (!settles) return;
    const timer = setTimeout(() => setSettledState(state), Math.max(0, settleMs));
    return () => clearTimeout(timer);
  }, [settleMs, settles, state]);
  return settles && settledState === state;
}
/** Client-only canvas with reduced-motion support and resting-state settling. */
export function AiOrb({ state, size = "lg", label, decorative = false, colorToken, settleMs = 5000, className, ...rest }: AiOrbProps) {
  const visual = VISUALS[state];
  const reduced = useReducedMotion() ?? false;
  const settled = useSettled(state, visual.settles, settleMs);
  const host = useRef<HTMLSpanElement>(null);
  const color = useOrbColor(host, visual.tone, colorToken);
  const mounted = useSyncExternalStore(noop, () => true, () => false);
  const preset = SIZE[size];
  const a11y = decorative ? { "aria-hidden": true } : { "aria-label": label ?? AI_ORB_LABELS[state], role: "img" };
  return <span {...rest} {...a11y} className={cn("relative inline-block shrink-0", preset.box, className)} data-orb={visual.orb} data-slot="ai-orb" data-state={state} ref={host}>
    {mounted ? <AnimatePresence initial={false}><motion.span animate={{ opacity: 1 }} className="absolute inset-0" exit={{ opacity: 0 }} initial={{ opacity: 0 }} key={`${visual.orb}-${visual.tone}`} transition={reduced ? { duration: 0 } : { duration: 0.2 }}>
      <ThinkingOrb aria-hidden color={color} dotSize={preset.dot} paused={visual.paused || reduced || settled} size={preset.px} speed={visual.speed} state={visual.orb} />
    </motion.span></AnimatePresence> : null}
  </span>;
}
export default AiOrb;
