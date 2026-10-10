"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Point = { date: string; calls: number; connected: number; booked: number };

const SERIES = [
  { key: "calls", label: "Dialed", color: "#a89f98" },
  { key: "connected", label: "Connected", color: "#dc4a1e" },
  { key: "booked", label: "Booked", color: "#047857" },
] as const;

function shortDate(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number }[]; label?: string }) {
  if (!active || !payload?.length || !label) return null;
  return (
    <div className="min-w-36 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="mb-1.5 font-medium text-zinc-900">{shortDate(label)}</div>
      {SERIES.map((s) => {
        const v = payload.find((p) => p.dataKey === s.key)?.value ?? 0;
        return (
          <div key={s.key} className="flex items-center justify-between gap-4 py-0.5">
            <span className="flex items-center gap-1.5 text-zinc-500">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: s.color }} />
              {s.label}
            </span>
            <span className="font-mono tabular-nums text-zinc-900">{v}</span>
          </div>
        );
      })}
    </div>
  );
}

export function CallVolumeChart({ data }: { data: Point[] }) {
  const every = Math.max(1, Math.ceil(data.length / 8));
  return (
    <div>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ left: 0, right: 24, top: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="bsConnected" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#dc4a1e" stopOpacity={0.28} />
                <stop offset="100%" stopColor="#dc4a1e" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="#e7e3df" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              interval={every - 1}
              tickFormatter={shortDate}
              tick={{ fill: "#746963", fontSize: 11 }}
            />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={30} tick={{ fill: "#746963", fontSize: 11 }} />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "#d6d0ca" }} />
            {/* Series separate by form as well as color: dashed dialed, filled connected, solid booked. */}
            <Area dataKey="calls" type="monotone" stroke="#a89f98" strokeDasharray="4 4" strokeWidth={2} fill="none" />
            <Area dataKey="connected" type="monotone" stroke="#dc4a1e" strokeWidth={2} fill="url(#bsConnected)" />
            <Area dataKey="booked" type="monotone" stroke="#047857" strokeWidth={2} fill="none" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-center gap-4 text-xs text-zinc-500">
        {SERIES.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-[2px]" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
