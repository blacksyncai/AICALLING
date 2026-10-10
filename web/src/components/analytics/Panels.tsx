"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";
import { OUTCOME_TONE, cn, humanize } from "@/lib/utils";
import { pct, type AgentRow, type Analytics, type CampaignRow, type Funnel } from "./types";

const TONE_BG: Record<string, string> = {
  green: "bg-emerald-600",
  blue: "bg-blue-500",
  violet: "bg-violet-500",
  amber: "bg-amber-500",
  red: "bg-red-500",
  gray: "bg-zinc-400",
};

const STEPS: { key: keyof Funnel; label: string; hint: string; verb: string }[] = [
  { key: "dialed", label: "Dialed", hint: "Calls placed", verb: "" },
  { key: "connected", label: "Connected", hint: "Someone picked up", verb: "picked up" },
  { key: "conversations", label: "Conversations", hint: "Talked for 30 seconds or more", verb: "kept talking" },
  { key: "qualified", label: "Qualified", hint: "Interested, qualified, transferred or booked", verb: "were a good fit" },
  { key: "booked", label: "Booked", hint: "Meeting on the calendar", verb: "booked a meeting" },
];

export function FunnelChart({ funnel }: { funnel: Funnel }) {
  const top = funnel.dialed || 1;
  return (
    <ol className="flex flex-col">
      {STEPS.map((s, i) => {
        const value = funnel[s.key];
        const prev = i > 0 ? funnel[STEPS[i - 1].key] : 0;
        const width = Math.max(value ? 2 : 0, (value / top) * 100);
        return (
          <Fragment key={s.key}>
            {i > 0 && (
              <li aria-hidden className="flex items-center gap-1.5 py-1 pl-1 text-xs text-zinc-500">
                <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
                <span className="font-medium tabular-nums text-zinc-700">{pct(value, prev)}%</span> {s.verb}
              </li>
            )}
            <li className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-zinc-900">
                  {s.label} <span className="hidden font-normal text-zinc-500 sm:inline">· {s.hint}</span>
                </span>
                <span className="shrink-0 text-sm tabular-nums">
                  <span className="font-display text-base font-semibold">{value.toLocaleString()}</span>
                  {i > 0 && <span className="ml-1.5 text-xs text-zinc-500">{pct(value, funnel.dialed)}% of dialed</span>}
                </span>
              </div>
              <div className="h-3 overflow-hidden rounded-full bg-zinc-100">
                <div
                  className={cn("h-full rounded-full transition-all", s.key === "booked" ? "bg-emerald-600" : "brand-gradient")}
                  style={{ width: `${width}%` }}
                />
              </div>
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}

export function OutcomeBars({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = Object.entries(outcomes).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((a, [, n]) => a + n, 0);
  const max = rows[0]?.[1] || 1;
  return (
    <ul className="flex flex-col gap-3">
      {rows.map(([outcome, n]) => (
        <li key={outcome} className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate text-zinc-700">{outcome === "in_progress" ? "In progress" : humanize(outcome)}</span>
          <div className="h-2.5 overflow-hidden rounded-full bg-zinc-100">
            <div className={cn("h-full rounded-full", TONE_BG[OUTCOME_TONE[outcome] ?? "gray"])} style={{ width: `${(n / max) * 100}%` }} />
          </div>
          <span className="w-16 text-right text-xs tabular-nums text-zinc-500">
            <span className="font-medium text-zinc-900">{n}</span> · {pct(n, total)}%
          </span>
        </li>
      ))}
    </ul>
  );
}

export function SentimentBar({ sentiment }: { sentiment: Analytics["sentiment"] }) {
  const parts = [
    { key: "positive", label: "Positive", color: "bg-emerald-600", n: sentiment.positive },
    { key: "neutral", label: "Neutral", color: "bg-zinc-300", n: sentiment.neutral },
    { key: "negative", label: "Negative", color: "bg-red-500", n: sentiment.negative },
  ];
  const total = parts.reduce((a, p) => a + p.n, 0);
  if (!total) return <p className="text-sm text-zinc-500">No mood readings yet — they appear once calls are analyzed.</p>;
  return (
    <div>
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-zinc-100" role="img" aria-label={parts.map((p) => `${p.label} ${pct(p.n, total)}%`).join(", ")}>
        {parts.map((p) => p.n > 0 && <div key={p.key} className={p.color} style={{ width: `${(p.n / total) * 100}%` }} />)}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-zinc-500">
        {parts.map((p) => (
          <span key={p.key} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-[2px]", p.color)} />
            {p.label}
            <span className="font-medium tabular-nums text-zinc-900">{pct(p.n, total)}%</span>
            <span className="tabular-nums">({p.n})</span>
          </span>
        ))}
      </div>
    </div>
  );
}

const th = "px-4 py-2.5 text-left text-xs font-medium text-zinc-500 whitespace-nowrap";
const td = "px-4 py-3 whitespace-nowrap tabular-nums";

export function AgentTable({ rows }: { rows: AgentRow[] }) {
  if (!rows.length) return <p className="px-5 pb-5 text-sm text-zinc-500">No phone calls from agents in this period.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-y border-zinc-100 bg-zinc-50/60">
          <tr>
            <th className={th}>Agent</th>
            <th className={cn(th, "text-right")}>Calls</th>
            <th className={cn(th, "text-right")}>Connect rate</th>
            <th className={cn(th, "text-right")}>Booked</th>
            <th className={cn(th, "text-right")}>Booking rate</th>
            <th className={cn(th, "text-right")}>Talk time</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {rows.map((r, i) => (
            <tr key={r.agent_id ?? `none-${i}`} className="hover:bg-zinc-50">
              <td className={cn(td, "max-w-48 truncate font-medium")}>
                {r.agent_id ? <Link href={`/agents/${r.agent_id}`} className="hover:text-brand-700">{r.name}</Link> : r.name}
              </td>
              <td className={cn(td, "text-right")}>{r.calls}</td>
              <td className={cn(td, "text-right")}>{Math.round(r.connect_rate * 100)}%</td>
              <td className={cn(td, "text-right font-medium text-emerald-700")}>{r.booked}</td>
              <td className={cn(td, "text-right")}>{Math.round(r.book_rate * 100)}%</td>
              <td className={cn(td, "text-right text-zinc-500")}>{r.minutes} min</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CampaignTable({ rows }: { rows: CampaignRow[] }) {
  if (!rows.length) return <p className="px-5 pb-5 text-sm text-zinc-500">No campaign calls in this period.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-y border-zinc-100 bg-zinc-50/60">
          <tr>
            <th className={th}>Campaign</th>
            <th className={cn(th, "text-right")}>Calls</th>
            <th className={cn(th, "text-right")}>Connected</th>
            <th className={cn(th, "text-right")}>Booked</th>
            <th className={cn(th, "text-right")}>Booking rate</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {rows.map((r) => (
            <tr key={r.campaign_id} className="hover:bg-zinc-50">
              <td className={cn(td, "max-w-48 truncate font-medium")}>
                <Link href={`/campaigns/${r.campaign_id}`} className="hover:text-brand-700">{r.name}</Link>
              </td>
              <td className={cn(td, "text-right")}>{r.calls}</td>
              <td className={cn(td, "text-right")}>{r.connected}</td>
              <td className={cn(td, "text-right font-medium text-emerald-700")}>{r.booked}</td>
              <td className={cn(td, "text-right")}>{Math.round(r.book_rate * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
