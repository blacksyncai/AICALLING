"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export type Units = "credits" | "usd";
const KEY = "bs-billing-units";

/** Credits ⇄ approximate dollars. Remembered per browser; it's a display preference only. */
export function useUnits(): [Units, (u: Units) => void] {
  const [units, setUnits] = useState<Units>("credits");
  useEffect(() => {
    try {
      if (localStorage.getItem(KEY) === "usd") setUnits("usd");
    } catch {
      /* storage unavailable */
    }
  }, []);
  const set = (u: Units) => {
    setUnits(u);
    try {
      localStorage.setItem(KEY, u);
    } catch {
      /* storage unavailable */
    }
  };
  return [units, set];
}

export function UnitsToggle({ units, onChange }: { units: Units; onChange: (u: Units) => void }) {
  return (
    <div className="inline-flex rounded-lg bg-zinc-100 p-0.5 text-xs font-medium" role="group" aria-label="Show amounts in">
      {(["credits", "usd"] as const).map((u) => (
        <button
          key={u}
          type="button"
          onClick={() => onChange(u)}
          aria-pressed={units === u}
          className={cn("rounded-md px-2.5 py-1 transition-colors", units === u ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-800")}
        >
          {u === "credits" ? "Credits" : "$ estimate"}
        </button>
      ))}
    </div>
  );
}

/** "1,234 credits" or "≈ $321" — dollars are an estimate from what was paid, never a cash balance. */
export function amount(credits: number, units: Units, centsPerCredit: number): string {
  if (units === "credits") return `${credits.toLocaleString()} credit${credits === 1 ? "" : "s"}`;
  const dollars = (credits * centsPerCredit) / 100;
  return `≈ $${dollars.toLocaleString(undefined, { maximumFractionDigits: dollars < 100 ? 2 : 0 })}`;
}
