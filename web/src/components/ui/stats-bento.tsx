"use client";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type BentoStat = { label: string; value: string; note?: ReactNode; icon?: LucideIcon };

/**
 * Bento grid of headline numbers: one large dark hero, a wide stat with a mini bar chart,
 * a compact stat, an icon stat, and an optional row of extra stats underneath.
 */
export function StatsBento({
  hero,
  trend,
  compact,
  feature,
  extras = [],
}: {
  hero: BentoStat & { badge?: string };
  trend: BentoStat & { bars: number[]; barsLabel?: string };
  compact: BentoStat;
  feature: BentoStat;
  extras?: BentoStat[];
}) {
  const max = Math.max(1, ...trend.bars);
  const FeatureIcon = feature.icon;
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-6 md:grid-rows-[auto_auto]">
      {/* Hero */}
      <div className="relative flex min-h-[220px] flex-col justify-between overflow-hidden rounded-3xl bg-zinc-950 p-7 sm:col-span-2 md:col-span-3 md:row-span-2 md:p-9">
        <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(45deg,#a1a1aa_0px_1px,transparent_1px_10px)] opacity-20 mask-[radial-gradient(ellipse_80%_60%_at_100%_0%,#000_60%,transparent_110%)]" />
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-brand-500/25 blur-3xl" />
        <div className="relative">
          <span className="mb-6 inline-block rounded-full bg-white/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-widest text-white/60">
            {hero.badge ?? hero.label}
          </span>
          <h3 className="font-display text-6xl font-semibold tabular-nums tracking-tighter text-white">{hero.value}</h3>
          {hero.badge && <p className="mt-1 text-sm font-medium text-white/70">{hero.label}</p>}
        </div>
        {hero.note && <div className="relative max-w-xs text-sm text-white/60">{hero.note}</div>}
      </div>

      {/* Wide stat with bars */}
      <div className="flex items-center justify-between gap-4 rounded-3xl border border-zinc-200/80 bg-zinc-100/70 p-6 sm:col-span-2 md:col-span-3 md:p-8">
        <div className="min-w-0">
          <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-zinc-500">{trend.label}</p>
          <p className="font-display text-3xl font-semibold tabular-nums tracking-tight text-zinc-900">{trend.value}</p>
          {trend.note && <div className="mt-1 text-xs">{trend.note}</div>}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <div className="flex h-10 items-end gap-1" aria-hidden>
            {trend.bars.map((v, i) => (
              <div
                key={i}
                className={cn("w-1.5 rounded-full", v ? "bg-zinc-900" : "bg-zinc-300")}
                style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
              />
            ))}
          </div>
          {trend.barsLabel && <span className="text-[10px] text-zinc-400">{trend.barsLabel}</span>}
        </div>
      </div>

      {/* Compact stat */}
      <div className="flex flex-col justify-center rounded-3xl border border-zinc-200/80 bg-white p-6 text-center md:col-span-1">
        <p className="font-display text-2xl font-semibold tabular-nums text-zinc-900">{compact.value}</p>
        <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-500">{compact.label}</p>
        {compact.note && <div className="mt-1 text-[11px]">{compact.note}</div>}
      </div>

      {/* Icon stat */}
      <div className="flex items-center gap-4 rounded-3xl bg-brand-50/70 p-6 ring-1 ring-inset ring-brand-100 md:col-span-2">
        {FeatureIcon && (
          <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-white text-brand-600 shadow-sm">
            <FeatureIcon className="h-5 w-5" />
          </div>
        )}
        <div className="min-w-0">
          <p className="font-display text-lg font-semibold leading-none tabular-nums text-zinc-900">{feature.value}</p>
          <p className="mt-1 text-xs font-semibold text-zinc-600">{feature.label}</p>
          {feature.note && <div className="mt-0.5 text-[11px] text-zinc-500">{feature.note}</div>}
        </div>
      </div>

      {/* Extras */}
      {extras.map((s) => {
        const Icon = s.icon;
        return (
          <div key={s.label} className="flex items-start justify-between gap-3 rounded-3xl border border-zinc-200/80 bg-white p-6 sm:col-span-1 md:col-span-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">{s.label}</p>
              <p className="mt-1 font-display text-3xl font-semibold tabular-nums tracking-tight text-zinc-900">{s.value}</p>
              {s.note && <div className="mt-1 text-xs">{s.note}</div>}
            </div>
            {Icon && (
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-zinc-100 text-zinc-600">
                <Icon className="h-4 w-4" />
              </span>
            )}
          </div>
        );
      })}
    </section>
  );
}

export default StatsBento;
