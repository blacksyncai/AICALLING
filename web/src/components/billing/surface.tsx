"use client";

import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// Soft, borderless surfaces for the billing pages (no grid lines — rows separate by spacing and hover).

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-2xl bg-white shadow-[0_1px_3px_rgba(33,27,24,0.05),0_8px_24px_-12px_rgba(33,27,24,0.08)] ring-1 ring-zinc-900/[0.06]", className)}>{children}</div>;
}

export function CardHeader({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 px-6 pb-2 pt-5">
      <div>
        <h3 className="text-[15px] font-semibold tracking-tight text-zinc-900">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/** Rounded pill action, like the ones in chat apps. */
export function PillAction({ onClick, children, tone = "dark" }: { onClick: () => void; children: ReactNode; tone?: "dark" | "light" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-sm font-medium transition active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
        tone === "dark" ? "bg-zinc-900 text-white hover:bg-zinc-800" : "bg-zinc-100 text-zinc-800 hover:bg-zinc-200/80",
      )}
    >
      {children}
      <ArrowRight className="h-3.5 w-3.5" />
    </button>
  );
}

export const listCls = "flex flex-col gap-0.5 px-3 pb-3 text-sm";
export const rowCls = "rounded-xl px-3 py-2.5 transition-colors hover:bg-zinc-50";
export const emptyCls = "px-6 pb-6 pt-2 text-sm text-zinc-500";
