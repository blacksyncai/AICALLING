"use client";

import { Loader2, X } from "lucide-react";
import type React from "react";
import { forwardRef, useEffect, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  className,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }) {
  return (
    <button
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-[background-color,box-shadow,transform,color] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
        size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm",
        variant === "primary" &&
          "bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-[0_1px_2px_rgba(185,58,20,0.35),inset_0_1px_0_rgba(255,255,255,0.18)] hover:from-brand-600 hover:to-brand-700",
        variant === "secondary" && "border border-zinc-200 bg-white text-zinc-800 shadow-xs hover:border-zinc-300 hover:bg-zinc-50",
        variant === "ghost" && "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
        variant === "danger" && "bg-red-600 text-white shadow-[0_1px_2px_rgba(185,28,28,0.3)] hover:bg-red-700",
        className,
      )}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-xl border border-zinc-200/80 bg-white shadow-[0_1px_2px_rgba(33,27,24,0.04),0_2px_8px_-2px_rgba(33,27,24,0.05)]", className)}>
      {children}
    </div>
  );
}

export function CardHeader({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-5 py-4">
      <div>
        <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-[26px] font-semibold leading-tight tracking-tight text-zinc-900">{title}</h1>
        {description && <p className="mt-1.5 text-sm text-zinc-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

const fieldBase =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-900 shadow-xs transition-[border-color,box-shadow] placeholder:text-zinc-400 hover:border-zinc-300 focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-500/10 disabled:bg-zinc-50 disabled:text-zinc-500";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={cn(fieldBase, "h-9", className)} {...props} />;
});

export function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return <textarea className={cn(fieldBase, "py-2 leading-relaxed", className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(fieldBase, "h-9 pr-8", className)} {...props}>
      {children}
    </select>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-xs font-medium text-zinc-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex w-full items-start justify-between gap-4 rounded-lg border border-zinc-200 p-3 text-left transition-colors hover:border-zinc-300 hover:bg-zinc-50/60"
    >
      <span>
        <span className="block text-sm font-medium text-zinc-900">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-zinc-500">{description}</span>}
      </span>
      <span className={cn("relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors duration-200", checked ? "bg-brand-600" : "bg-zinc-300")}>
        <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-all duration-200", checked ? "left-[18px]" : "left-0.5")} />
      </span>
    </button>
  );
}

const tones = {
  gray: "bg-zinc-100 text-zinc-700",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  blue: "bg-blue-50 text-blue-700 ring-blue-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/20",
  brand: "bg-brand-50 text-brand-700 ring-brand-600/20",
};

export function Badge({ tone = "gray", children, className }: { tone?: keyof typeof tones; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-transparent", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-zinc-950/40 p-4 pt-[10vh] backdrop-blur-[2px] transition-opacity duration-200 starting:opacity-0"
      onMouseDown={onClose}
    >
      <div
        className={cn(
          "w-full rounded-2xl bg-white shadow-2xl ring-1 ring-zinc-900/5 transition duration-200 ease-out starting:translate-y-2 starting:scale-[0.98] starting:opacity-0",
          wide ? "max-w-3xl" : "max-w-lg",
        )}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal
      >
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-4">
          <h2 className="font-display text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: string; icon?: ReactNode }[] }) {
  return (
    <div className="flex gap-1 rounded-xl bg-zinc-100/80 p-1 ring-1 ring-inset ring-zinc-200/60">
      {tabs.map((t) => (
        <button
          key={t.value}
          onClick={() => onChange(t.value)}
          className={cn(
            "flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-150",
            value === t.value ? "bg-white text-zinc-900 shadow-[0_1px_2px_rgba(33,27,24,0.08),0_1px_1px_rgba(33,27,24,0.04)]" : "text-zinc-500 hover:text-zinc-800",
          )}
        >
          {t.icon}
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: { icon: ReactNode; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-b from-brand-50 to-brand-100/70 text-brand-600 ring-1 ring-inset ring-brand-200/60">{icon}</div>
      <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-zinc-500">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-5 w-5 animate-spin text-zinc-400", className)} />;
}

export function Notice({ tone = "amber", children }: { tone?: "amber" | "red" | "blue" | "green"; children: ReactNode }) {
  const cls = {
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    red: "border-red-200 bg-red-50 text-red-800",
    blue: "border-blue-200 bg-blue-50 text-blue-900",
    green: "border-emerald-200 bg-emerald-50 text-emerald-900",
  }[tone];
  return <div className={cn("rounded-lg border px-3 py-2.5 text-xs leading-relaxed", cls)}>{children}</div>;
}
