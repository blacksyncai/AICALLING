"use client";

import NumberFlow from "@number-flow/react";
import { Check, Loader2 } from "lucide-react";
import { motion, type Variants } from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { VerticalCutReveal } from "./vertical-cut-reveal";

const reveal: Variants = {
  hidden: { opacity: 0, y: -16, filter: "blur(8px)" },
  visible: (i: number) => ({ opacity: 1, y: 0, filter: "blur(0px)", transition: { delay: i * 0.12, duration: 0.45 } }),
};

/** Fades/blur-reveals its children in order. */
export function Reveal({ index = 0, className, children }: { index?: number; className?: string; children: ReactNode }) {
  return (
    <motion.div custom={index} variants={reveal} initial="hidden" animate="visible" className={className}>
      {children}
    </motion.div>
  );
}

/** Section title with the word-by-word reveal and a short subtitle. */
export function PricingHeading({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl">
          <VerticalCutReveal reverse>{title}</VerticalCutReveal>
        </h2>
        {description && (
          <Reveal>
            <p className="mt-1.5 text-sm text-zinc-600">{description}</p>
          </Reveal>
        )}
      </div>
      {action}
    </div>
  );
}

/** "$98" that counts to its value (USD, whole or cents). */
export function Price({ cents, className }: { cents: number; className?: string }) {
  const value = cents / 100;
  return (
    <NumberFlow
      value={value}
      format={{ style: "currency", currency: "USD", maximumFractionDigits: Number.isInteger(value) ? 0 : 2 }}
      className={cn("font-display font-semibold tabular-nums tracking-tight text-zinc-900", className)}
    />
  );
}

export function CheckItem({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-content-center rounded-full border border-brand-500 bg-white">
        <Check className="h-3 w-3 text-brand-600" strokeWidth={3} />
      </span>
      <span className="text-sm text-zinc-700">{children}</span>
    </li>
  );
}

/** Big pricing CTA: orange for the highlighted card, near-black for the rest. */
export function PricingButton({
  tone = "dark",
  loading,
  disabled,
  onClick,
  children,
}: {
  tone?: "brand" | "dark" | "muted";
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        "flex h-12 w-full items-center justify-center gap-2 rounded-xl text-sm font-semibold transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
        tone === "brand" && "border border-brand-400 bg-gradient-to-t from-brand-600 to-brand-500 text-white shadow-lg shadow-brand-500/30 hover:from-brand-700 hover:to-brand-600",
        tone === "dark" && "border border-zinc-700 bg-gradient-to-t from-zinc-950 to-zinc-700 text-white shadow-lg shadow-zinc-900/20 hover:to-zinc-800",
        tone === "muted" && "border border-zinc-200 bg-white text-zinc-500",
      )}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

/** One plan / pack card in the BlackSync pricing style. */
export function PricingCard({
  index = 0,
  name,
  description,
  cents,
  period,
  badge,
  highlighted,
  features,
  featuresTitle,
  footer,
}: {
  index?: number;
  name: string;
  description?: ReactNode;
  cents: number;
  /** "month" → "/month"; omit for one-time prices. */
  period?: string;
  badge?: ReactNode;
  highlighted?: boolean;
  features?: ReactNode[];
  featuresTitle?: string;
  footer: ReactNode;
}) {
  return (
    <Reveal index={index} className="h-full">
      <div
        className={cn(
          "relative flex h-full flex-col rounded-2xl border p-6 transition-shadow",
          highlighted ? "border-brand-200 bg-brand-50/60 shadow-sm ring-2 ring-brand-500" : "border-zinc-200 bg-white hover:shadow-md",
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-xl font-semibold text-zinc-900">{name}</h3>
          {badge}
        </div>
        {description && <p className="mt-1 text-sm text-zinc-600">{description}</p>}
        <div className="mt-4 flex items-baseline gap-1">
          <Price cents={cents} className="text-4xl" />
          {period && <span className="text-sm text-zinc-500">/{period}</span>}
        </div>
        <div className="mt-5">{footer}</div>
        {features && features.length > 0 && (
          <div className="mt-6 flex-1 border-t border-zinc-200/80 pt-5">
            {featuresTitle && <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-zinc-500">{featuresTitle}</p>}
            <ul className="space-y-2.5">
              {features.map((f, i) => (
                <CheckItem key={i}>{f}</CheckItem>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Reveal>
  );
}

export function PillBadge({ children, tone = "brand" }: { children: ReactNode; tone?: "brand" | "dark" }) {
  return (
    <span className={cn("shrink-0 rounded-full px-3 py-1 text-xs font-semibold", tone === "brand" ? "bg-brand-500 text-white" : "bg-zinc-900 text-white")}>
      {children}
    </span>
  );
}

/** Orange sliding segmented control (from the pricing switch), used for the billing tabs. */
export function PillTabs<T extends string>({
  value,
  onChange,
  tabs,
  layoutId = "pill-tabs",
}: {
  value: T;
  onChange: (v: T) => void;
  tabs: { value: T; label: string; icon?: ReactNode }[];
  layoutId?: string;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const selected = useRef<HTMLButtonElement>(null);
  // Keep the selected tab visible when the bar scrolls sideways (phones) without moving the page.
  useEffect(() => {
    const b = bar.current;
    const t = selected.current;
    if (b && t) b.scrollLeft = t.offsetLeft - (b.clientWidth - t.offsetWidth) / 2;
  }, [value]);
  return (
    <div ref={bar} className="-mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
      <div role="tablist" className="relative inline-flex min-w-max gap-1 rounded-xl border border-zinc-200 bg-white/70 p-1">
        {tabs.map((t) => {
          const active = t.value === value;
          return (
            <button
              key={t.value}
              ref={active ? selected : undefined}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(t.value)}
              className={cn(
                "relative flex h-9 items-center gap-1.5 rounded-lg px-3.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-brand-500",
                active ? "text-white" : "text-zinc-500 hover:text-zinc-900",
              )}
            >
              {active && (
                <motion.span
                  layoutId={layoutId}
                  className="absolute inset-0 rounded-lg bg-gradient-to-t from-brand-600 to-brand-500 shadow-sm shadow-brand-600/40"
                  transition={{ type: "spring", stiffness: 500, damping: 35 }}
                />
              )}
              <span className="relative flex items-center gap-1.5">
                {t.icon}
                {t.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
