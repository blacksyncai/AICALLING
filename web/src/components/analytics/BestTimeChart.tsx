"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { rangeLabel, shortHour, type LocalHour } from "./hours";

type Point = LocalHour & { pct: number };

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  return (
    <div className="min-w-40 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="mb-1.5 font-medium text-zinc-900">{rangeLabel(p.hour, p.hour + 1)}</div>
      <div className="flex justify-between gap-4 py-0.5 text-zinc-500">
        Connect rate <span className="font-mono tabular-nums text-zinc-900">{p.calls ? `${p.pct}%` : "—"}</span>
      </div>
      <div className="flex justify-between gap-4 py-0.5 text-zinc-500">
        Answered <span className="font-mono tabular-nums text-zinc-900">{p.connected} of {p.calls}</span>
      </div>
    </div>
  );
}

export function BestTimeChart({ hours, best }: { hours: LocalHour[]; best: number[] }) {
  // Trim to the span of hours that actually had calls (plus a little padding).
  const active = hours.filter((h) => h.calls > 0).map((h) => h.hour);
  const from = active.length ? Math.max(0, Math.min(...active) - 1) : 8;
  const to = active.length ? Math.min(23, Math.max(...active) + 1) : 18;
  const data: Point[] = hours.slice(from, to + 1).map((h) => ({ ...h, pct: Math.round(h.rate * 100) }));
  const every = Math.max(1, Math.ceil(data.length / 8));

  return (
    <div>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#e7e3df" strokeDasharray="3 3" />
            <XAxis
              dataKey="hour"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              interval={every - 1}
              tickFormatter={shortHour}
              tick={{ fill: "#746963", fontSize: 11 }}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v: number) => `${v}%`}
              tickLine={false}
              axisLine={false}
              width={36}
              tick={{ fill: "#746963", fontSize: 11 }}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: "#f4f1ee" }} />
            <Bar dataKey="pct" radius={[4, 4, 0, 0]} maxBarSize={28}>
              {data.map((d) => (
                <Cell key={d.hour} fill={best.includes(d.hour) ? "#dc4a1e" : "#d6d0ca"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-center gap-4 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-[2px]" style={{ background: "#dc4a1e" }} />
          Best hours
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-[2px]" style={{ background: "#d6d0ca" }} />
          Other hours
        </span>
      </div>
    </div>
  );
}
