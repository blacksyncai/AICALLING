"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { Button, Card, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Stats } from "./types";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-5">
      <div className="text-sm font-medium text-zinc-600">{label}</div>
      <div className="mt-2 font-display text-3xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </Card>
  );
}

function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Track Desk → Weekly stats, counted from the check-in log. */
export function StatsTab() {
  const [offset, setOffset] = useState(0);
  const ref = new Date(Date.now() - offset * 7 * 86400000);
  const { data } = useSWR<Stats>(`/api/track-desk/stats?week=${isoDay(ref)}`, fetcher);
  if (!data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const start = new Date(data.week_start);
  const end = new Date(new Date(data.week_end).getTime() - 1);
  const fmt = (d: Date) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={() => setOffset(offset + 1)} aria-label="Previous week"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="text-sm font-medium text-zinc-800">{fmt(start)} – {fmt(end)}</span>
        <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset(offset - 1)} aria-label="Next week"><ChevronRight className="h-4 w-4" /></Button>
        <span className="ml-auto text-xs text-zinc-500">
          {data.loads_added} loads added this week{data.plan_limit ? ` of ${data.plan_limit} on your plan` : ""}
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Loads tracked" value={String(data.loads_tracked)} hint={`${data.loads_delivered} delivered`} />
        <Tile label="Check-ins logged" value={String(data.check_ins)} hint={`${data.calls} calls · ${data.texts_sent} texts`} />
        <Tile label="Answer rate" value={data.answer_rate === null ? "—" : `${Math.round(data.answer_rate * 100)}%`}
              hint={`${data.calls_answered} calls answered · ${data.text_replies} text replies`} />
        <Tile label="Hours saved" value={String(data.hours_saved)} hint="About 5 minutes per automated check-in" />
        <Tile label="Late loads flagged" value={String(data.late_flagged)} hint={`${data.late_flagged_early} before the delivery window closed`} />
        <Tile label="At risk" value={String(data.at_risk)} />
        <Tile label="Unresponsive drivers" value={String(data.unresponsive)} hint="Call, text and a second call went unanswered" />
      </div>
    </div>
  );
}
