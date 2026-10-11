"use client";

/**
 * Score gauge cards — a half-circle gauge with an animated arc and rolling digits.
 * Remixed from the "financial score cards" pattern for BlackSync: real data instead of
 * random scores, our Card styling instead of liquid-glass filters, no extra dependencies.
 */

import Link from "next/link";
import { useEffect, useId, useRef } from "react";
import { cn } from "@/lib/utils";

export type Strength = "none" | "weak" | "moderate" | "strong";

/** Strong at or above the target, moderate from half the target, weak below. */
export function strengthFor(value: number | null, target: number): Strength {
  if (value === null) return "none";
  if (value >= target) return "strong";
  if (value >= target / 2) return "moderate";
  return "weak";
}

const STOPS: Record<Strength, string[]> = {
  none: ["#d4d4d8", "#a1a1aa"],
  weak: ["#fecaca", "#f87171", "#dc2626"],
  moderate: ["#fde68a", "#fbbf24", "#d97706"],
  strong: ["#bbf7d0", "#4ade80", "#16a34a"],
};

const BADGE: Record<Exclude<Strength, "none">, string> = {
  weak: "bg-red-50 text-red-700 ring-red-600/20",
  moderate: "bg-amber-50 text-amber-800 ring-amber-600/20",
  strong: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
};

const EASE = "cubic-bezier(0.65, 0, 0.35, 1)";
const R = 45;
const HALF = Math.PI * R; // half the circumference

/** The arc. `value` is 0–100 (null = no data yet). */
export function ScoreArc({ value, strength }: { value: number | null; strength: Strength }) {
  const ref = useRef<SVGCircleElement>(null);
  const gradId = `gauge-${useId().replace(/:/g, "")}`;
  const stops = STOPS[strength];
  const offset = value === null ? 0 : -(Math.min(Math.max(value, 0), 100) / 100) * HALF;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      el.style.strokeDashoffset = String(offset);
      return;
    }
    const anim = el.animate(
      [{ strokeDashoffset: "0" }, { strokeDashoffset: "0", offset: 0.25 }, { strokeDashoffset: String(offset) }],
      { duration: 1400, easing: EASE, fill: "forwards" },
    );
    return () => anim.cancel();
  }, [offset]);

  return (
    <svg className="mx-auto block h-32 w-auto max-w-full" viewBox="0 0 100 50" aria-hidden="true">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
          {stops.map((c, i) => (
            <stop key={i} offset={`${(100 / (stops.length - 1)) * i}%`} stopColor={c} />
          ))}
        </linearGradient>
      </defs>
      <g fill="none" strokeWidth="10" transform="translate(50, 50.5)">
        <circle className="stroke-zinc-100" r={R} />
        <circle ref={ref} stroke={`url(#${gradId})`} strokeDasharray={`${HALF} ${HALF}`} r={R} />
      </g>
    </svg>
  );
}

/** Digits that roll up into place. */
function RollingNumber({ text }: { text: string }) {
  return (
    <span className="relative inline-flex h-11 overflow-hidden" aria-hidden="true">
      {text.split("").map((ch, i) => (
        <span
          key={`${ch}-${i}`}
          className="inline-block transition duration-700 ease-out starting:translate-y-full starting:opacity-0 motion-reduce:transition-none"
          style={{ transitionDelay: `${300 + i * 90}ms` }}
        >
          {ch}
        </span>
      ))}
    </span>
  );
}

export interface ScoreCardProps {
  title: string;
  /** 0–100, or null when there's no data yet. */
  value: number | null;
  /** Percentage that counts as strong. */
  target: number;
  description: string;
  /** Small caption under the number, e.g. "42 of 120 calls". */
  caption?: string;
  action?: { label: string; href: string };
  /** Staggers the entrance when several cards sit together. */
  index?: number;
}

export function ScoreCard({ title, value, target, description, caption, action, index = 0 }: ScoreCardProps) {
  const strength = strengthFor(value, target);
  const rounded = value === null ? null : Math.round(value);
  return (
    <div
      className="flex min-w-0 flex-col rounded-xl border border-zinc-200 bg-white p-5 shadow-xs transition duration-500 ease-out starting:translate-y-3 starting:opacity-0 motion-reduce:transition-none"
      style={{ transitionDelay: `${index * 120}ms` }}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="truncate text-sm font-medium text-zinc-900">{title}</h3>
        {strength !== "none" && (
          <span className={cn("shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset", BADGE[strength])}>
            {strength}
          </span>
        )}
      </div>

      <div className="relative mt-4">
        <ScoreArc value={rounded} strength={strength} />
        <div className="absolute inset-x-0 bottom-0 text-center">
          <div className="font-display text-4xl font-semibold tabular-nums tracking-tight text-zinc-900">
            {rounded === null ? <span className="text-zinc-300">—</span> : <RollingNumber text={`${rounded}%`} />}
            <span className="sr-only">{rounded === null ? "No data yet" : `${rounded} percent`}</span>
          </div>
        </div>
      </div>
      <p className="mt-1 text-center text-[11px] font-medium uppercase tracking-wide text-zinc-400">
        {caption ?? (rounded === null ? "No data yet" : `Target ${target}%`)}
      </p>

      <p className="mt-3 flex-1 text-center text-xs leading-relaxed text-zinc-500">{description}</p>

      {action && (
        <Link
          href={action.href}
          className="mt-4 inline-flex h-9 items-center justify-center rounded-lg border border-zinc-200 text-sm font-medium text-zinc-800 transition-colors hover:bg-zinc-50"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}

/** A responsive row of score cards. */
export function ScoreCards({ items }: { items: ScoreCardProps[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((item, i) => (
        <ScoreCard key={item.title} {...item} index={i} />
      ))}
    </div>
  );
}
