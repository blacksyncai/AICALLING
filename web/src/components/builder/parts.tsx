"use client";

import {
  Briefcase,
  Building2,
  Car,
  Check,
  ChevronDown,
  CircleDot,
  HeartPulse,
  Home,
  Landmark,
  LineChart,
  ShieldCheck,
  Truck,
  UserSearch,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const STEPS = ["Business", "Goal", "Personality", "Tools", "Review", "Done"] as const;

/** Icon for an industry. The catalog sends a lucide-style icon name; fall back to the industry key. */
const ICONS: Record<string, LucideIcon> = {
  home: Home,
  house: Home,
  real_estate: Home,
  landmark: Landmark,
  mortgage: Landmark,
  wrench: Wrench,
  hammer: Wrench,
  home_services: Wrench,
  stethoscope: HeartPulse,
  "heart-pulse": HeartPulse,
  heart: HeartPulse,
  healthcare: HeartPulse,
  shield: ShieldCheck,
  "shield-check": ShieldCheck,
  insurance: ShieldCheck,
  "line-chart": LineChart,
  "chart-line": LineChart,
  "trending-up": LineChart,
  "piggy-bank": LineChart,
  financial_services: LineChart,
  users: UserSearch,
  "user-search": UserSearch,
  recruiting: UserSearch,
  truck: Truck,
  logistics: Truck,
  car: Car,
  automotive: Car,
  briefcase: Briefcase,
  professional_services: Briefcase,
  building: Building2,
  "building-2": Building2,
  other: CircleDot,
};

export function industryIcon(icon: string | undefined, key: string | undefined): LucideIcon {
  return (icon && ICONS[icon]) || (key && ICONS[key]) || CircleDot;
}

export function normalizeUrl(raw: string): string {
  const v = raw.trim();
  if (!v) return "";
  return /^https?:\/\//i.test(v) ? v : `https://${v}`;
}

export function displayHost(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(normalizeUrl(url)).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function StepTitle({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-6">
      <h2 className="font-display text-xl font-semibold tracking-tight text-zinc-900 sm:text-2xl">{title}</h2>
      {description && <p className="mt-1 text-sm text-zinc-500">{description}</p>}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T | undefined;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex w-full gap-1 rounded-lg bg-zinc-100 p-1 sm:w-auto">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-brand-500 sm:flex-none sm:px-4",
            value === o.value ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-800",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A selectable row/card with a check mark when selected. */
export function OptionCard({
  selected,
  onClick,
  title,
  description,
  icon,
  badge,
  disabled,
  className,
  role = "radio",
}: {
  selected: boolean;
  onClick?: () => void;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  badge?: ReactNode;
  disabled?: boolean;
  className?: string;
  role?: "radio" | "checkbox";
}) {
  return (
    <button
      type="button"
      role={role}
      aria-checked={selected}
      aria-disabled={disabled || undefined}
      onClick={disabled ? undefined : onClick}
      className={cn(
        "flex w-full items-start gap-3 rounded-xl border p-3 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
        selected ? "border-brand-500 bg-brand-50/50 ring-1 ring-brand-500" : "border-zinc-200 bg-white hover:border-zinc-300 hover:bg-zinc-50",
        disabled && "cursor-not-allowed opacity-60 hover:border-zinc-200 hover:bg-white",
        className,
      )}
    >
      {icon && (
        <span
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            selected ? "bg-brand-600 text-white" : "bg-zinc-100 text-zinc-600",
          )}
        >
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-zinc-900">
          {title}
          {badge}
        </span>
        {description && <span className="mt-0.5 block text-xs leading-relaxed text-zinc-500">{description}</span>}
      </span>
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center border transition",
          role === "radio" ? "rounded-full" : "rounded",
          selected ? "border-brand-600 bg-brand-600 text-white" : "border-zinc-300 bg-white",
        )}
        aria-hidden
      >
        {selected && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
    </button>
  );
}

export function Collapsible({
  title,
  children,
  defaultOpen = false,
  meta,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  meta?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-zinc-200 bg-white">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-sm font-medium text-zinc-800 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-brand-500"
      >
        <span className="flex min-w-0 items-center gap-2">{title}</span>
        <span className="flex shrink-0 items-center gap-2 text-xs text-zinc-500">
          {meta}
          <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </span>
      </button>
      {open && <div className="border-t border-zinc-100 px-4 py-4">{children}</div>}
    </div>
  );
}

export function StepProgress({ step }: { step: number }) {
  const label = STEPS[step - 1];
  return (
    <>
      {/* Mobile */}
      <div className="sm:hidden">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-zinc-800">
            Step {step} of {STEPS.length} · {label}
          </span>
        </div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-zinc-100">
          <div className="h-full rounded-full bg-brand-600 transition-all duration-500" style={{ width: `${(step / STEPS.length) * 100}%` }} />
        </div>
      </div>
      {/* Desktop */}
      <ol className="hidden items-center sm:flex" aria-label="Progress">
        {STEPS.map((s, i) => {
          const n = i + 1;
          const done = n < step;
          const current = n === step;
          return (
            <li key={s} className={cn("flex items-center", i < STEPS.length - 1 && "flex-1")} aria-current={current ? "step" : undefined}>
              <span className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold transition-colors",
                    done && "bg-brand-600 text-white",
                    current && "bg-brand-50 text-brand-700 ring-2 ring-brand-500",
                    !done && !current && "bg-zinc-100 text-zinc-500",
                  )}
                >
                  {done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : n}
                </span>
                <span className={cn("text-xs font-medium", current ? "text-zinc-900" : "text-zinc-500")}>{s}</span>
              </span>
              {i < STEPS.length - 1 && <span className={cn("mx-3 h-px flex-1 transition-colors", done ? "bg-brand-500" : "bg-zinc-200")} />}
            </li>
          );
        })}
      </ol>
    </>
  );
}
