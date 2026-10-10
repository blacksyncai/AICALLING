"use client";

import { Coins } from "lucide-react";
import { Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { LeadFinderUsage } from "./types";

/** Lead-lookup credit balance (separate from calling credits). */
export function CreditsCard({ usage }: { usage: LeadFinderUsage | undefined }) {
  const empty = !!usage && !usage.unlimited && usage.credits <= 0;
  return (
    <Card className="h-fit p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
        <Coins className={cn("h-3.5 w-3.5", empty ? "text-amber-500" : "text-brand-500")} /> Lookup credits
      </div>
      <div className={cn("mt-1 font-display text-2xl font-semibold tabular-nums", empty ? "text-amber-700" : "text-zinc-900")}>
        {!usage ? "—" : usage.unlimited ? "Unlimited" : usage.credits.toLocaleString()}
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
        1 credit per owner found. No match or errors cost nothing. Separate from your calling credits.
      </p>
    </Card>
  );
}
