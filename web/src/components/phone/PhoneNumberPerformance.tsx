import { BarChart3 } from "lucide-react";
import { LeaderboardBars, type LeaderboardBarRow } from "@/components/ui/leaderboard-bars";
import { Card } from "@/components/ui";
import type { PhoneNumberItem } from "@/lib/types";

export function PhoneNumberPerformance({ numbers }: { numbers: PhoneNumberItem[] }) {
  if (!numbers.length) return null;
  const rows: LeaderboardBarRow[] = [...numbers]
    .sort((a,b) => (b.health?.pickup_rate ?? -1) - (a.health?.pickup_rate ?? -1))
    .map(n => {
      const h=n.health;
      const known=!!h && h.dials_7d>0 && h.pickup_rate!==null && Number.isFinite(h.pickup_rate);
      return {
        label:n.number,
        sub:[n.label,n.is_default ? "Default" : "",h?.resting_until ? "Resting" : ""].filter(Boolean).join(" · ") || undefined,
        value:known ? h.pickup_rate! * 100 : 0,
        valueLabel:known ? `${Math.round(h.pickup_rate! * 100)}%` : "—",
        color:n.is_default ? "#ea580c" : "#64748b",
        metrics:[h ? h.dials_7d.toLocaleString() : null,h ? h.dials_24h.toLocaleString() : null,h && h.avg_talk_seconds>0 ? `${h.avg_talk_seconds}s` : null],
        offside:!known,
        offsideTag:!known ? !h || h.dials_7d===0 ? "No call data" : "Rate unavailable" : undefined,
      };
    });
  return <Card className="mb-6 min-w-0 overflow-hidden">
    <details open className="group">
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-5 py-4">
        <div><h2 className="flex items-center gap-2 font-semibold text-zinc-900"><BarChart3 className="h-4 w-4 text-brand-600"/>Number performance</h2><p className="mt-1 text-xs text-zinc-500">Compare your active caller numbers over the last 7 days.</p></div>
        <span className="text-xs text-zinc-400 group-open:hidden">Show comparison</span>
        <span className="hidden text-xs text-zinc-400 group-open:inline">Hide comparison</span>
      </summary>
      <div className="px-5 pb-4">
        <LeaderboardBars rows={rows} rowLabel="Phone number" barLabel="Pickup rate · 7 days" columns={["Calls · 7d","Calls · 24h","Avg talk"]}/>
        <p className="mt-3 text-xs text-zinc-500">Pickup rate = answered calls ÷ dials. Numbers without a measured rate are listed separately. Swipe the comparison sideways on smaller screens.</p>
      </div>
    </details>
  </Card>;
}
