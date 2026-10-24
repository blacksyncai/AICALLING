"use client";

import { useState, type ReactNode } from "react";
import { cn, formatDuration, outcomeLabel } from "@/lib/utils";
import type { LocalHour } from "./hours";
import { shortHour } from "./hours";
import { pct, type Analytics, type Funnel } from "./types";

/* Call analytics as a bento grid in the BlackSync palette: one orange hero, dark cards for the
   two "how are we reaching people" views, light cards for everything else. Charts are plain SVG. */

const ORANGE = "#ff9a6e"; // accent on dark / orange cards
const NO_PERSON = new Set(["voicemail", "no_answer", "failed", "screened", "in_progress"]);

type Tone = "brand" | "dark" | "light";
const TONE: Record<Tone, string> = {
  brand: "bg-[linear-gradient(160deg,#f2774a_0%,#dc4a1e_55%,#b93a14_100%)] text-white shadow-[0_18px_40px_-24px_rgba(185,58,20,.7)]",
  dark: "bg-[linear-gradient(180deg,#2a2a2e_0%,#141416_100%)] text-white shadow-[0_18px_40px_-28px_rgba(0,0,0,.6)]",
  light: "border border-zinc-200/80 bg-white text-zinc-900 shadow-[0_1px_2px_rgba(0,0,0,.04)]",
};

export function BentoCard({ tone, className, children }: { tone: Tone; className?: string; children: ReactNode }) {
  return (
    <section className={cn("relative min-w-0 overflow-hidden rounded-[26px]", TONE[tone], className)}>
      {tone !== "light" && <div className="pointer-events-none absolute inset-0 rounded-[inherit] shadow-[inset_0_1px_0_rgba(255,255,255,.18)]" />}
      <div className="relative flex h-full flex-col p-5 sm:p-6">{children}</div>
    </section>
  );
}

const Ttl = ({ children }: { children: ReactNode }) => <div className="text-[17px] font-semibold tracking-tight">{children}</div>;
const Cap = ({ children, dark }: { children: ReactNode; dark?: boolean }) => (
  <div className={cn("text-[11px] font-semibold uppercase tracking-[.08em]", dark ? "text-white/55" : "text-zinc-500")}>{children}</div>
);
const Sub = ({ children, dark, className }: { children: ReactNode; dark?: boolean; className?: string }) => (
  <div className={cn("text-xs font-medium", dark ? "text-white/50" : "text-zinc-500", className)}>{children}</div>
);
const Big = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cn("text-[40px] font-extralight leading-none tracking-[-.04em] tabular-nums", className)}>{children}</div>
);

function smooth(P: [number, number][]) {
  if (!P.length) return "";
  let d = `M${P[0][0]},${P[0][1]}`;
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[i - 1] || P[i], p1 = P[i], p2 = P[i + 1], p3 = P[i + 2] || p2, k = 0.17;
    d += `C${p1[0] + (p2[0] - p0[0]) * k},${p1[1] + (p2[1] - p0[1]) * k} ${p2[0] - (p3[0] - p1[0]) * k},${p2[1] - (p3[1] - p1[1]) * k} ${p2[0]},${p2[1]}`;
  }
  return d;
}

/** Trailing average so weekends don't turn the trend into a saw blade. */
function rolling(values: number[], n: number) {
  return values.map((_, i) => {
    const w = values.slice(Math.max(0, i - n + 1), i + 1);
    return w.reduce((a, b) => a + b, 0) / w.length;
  });
}

/** Tick marks filled up to `share` (0–1). */
function Ticks({ share, n = 36 }: { share: number; n?: number }) {
  return (
    <svg viewBox={`0 0 ${n * 6} 20`} preserveAspectRatio="none" className="h-5 w-full" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <line key={i} x1={i * 6 + 3} x2={i * 6 + 3} y1={i % 6 === 0 ? 2 : 8} y2={20} stroke={share > 0 && i / (n - 1) <= share ? "#ec653c" : "#e4e4e7"} strokeWidth={1.6} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
}

/* ── Calls trend (hero) ─────────────────────────────────────────────────────── */

export function CallsHero({ data }: { data: Analytics }) {
  const f = data.funnel;
  const days = data.by_day ?? [];
  const [hover, setHover] = useState<number | null>(null);
  const W = 1000, H = 200, top = 16, bot = 34;
  const avgWindow = days.length > 14 ? 7 : 3;
  const dialed = rolling(days.map((d) => d.dialed), avgWindow);
  const picked = rolling(days.map((d) => d.connected), avgWindow);
  const max = Math.max(1, ...dialed) * 1.1;
  const X = (i: number) => (days.length < 2 ? W / 2 : (i / (days.length - 1)) * W);
  const Y = (v: number) => H - bot - (v / max) * (H - top - bot);
  const line = (vals: number[]) => smooth(vals.map((v, i) => [X(i), Y(v)] as [number, number]));
  const fill = days.length ? `${line(dialed)}L${W},${H - bot}L0,${H - bot}Z` : "";
  const label = (iso: string) => new Date(iso + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const marks = days.length > 2 ? [0, Math.round((days.length - 1) / 2), days.length - 1] : days.map((_, i) => i);
  const h = hover !== null ? days[hover] : null;
  const stats = [
    [`${pct(f.connected, f.dialed)}%`, "picked up"],
    [Math.round(data.total_minutes).toLocaleString(), "min talk time"],
    [f.booked.toLocaleString(), f.booked === 1 ? "meeting" : "meetings"],
  ];
  return (
    <BentoCard tone="brand" className="col-span-12 h-[380px] lg:col-span-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <Ttl>Calls placed</Ttl>
        <div className="flex gap-4 text-xs font-medium text-white/75">
          <span className="flex items-center gap-1.5"><i className="h-0.5 w-3.5 rounded bg-white" />Dialed</span>
          <span className="flex items-center gap-1.5"><i className="h-0.5 w-3.5 rounded bg-white/45" />Picked up</span>
          <span className="text-white/55">{avgWindow}-day average</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-2">
        <Big className="text-[60px]">{f.dialed.toLocaleString()}</Big>
        <div className="flex gap-5 pb-1.5">
          {stats.map(([v, k]) => (
            <div key={k}>
              <div className="font-mono text-[15px] font-semibold tabular-nums">{v}</div>
              <div className="text-[11px] font-medium text-white/65">{k}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="absolute inset-x-0 bottom-0 h-[150px] sm:h-[200px]" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden>
          <defs>
            <linearGradient id="calls-fill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#fff" stopOpacity=".22" />
              <stop offset="1" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0.33, 0.66].map((t) => (
            <line key={t} x1={0} x2={W} y1={top + (H - top - bot) * t} y2={top + (H - top - bot) * t} stroke="#fff" strokeOpacity={0.12} strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />
          ))}
          <path d={fill} fill="url(#calls-fill)" />
          <path d={line(picked)} fill="none" stroke="#fff" strokeOpacity={0.45} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          <path d={line(dialed)} fill="none" stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke" />
          {hover !== null && <line x1={X(hover)} x2={X(hover)} y1={top} y2={H - bot} stroke="#fff" strokeOpacity={0.5} vectorEffect="non-scaling-stroke" />}
        </svg>
        {hover !== null && (
          <span className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white ring-4 ring-white/25" style={{ left: `${(X(hover) / W) * 100}%`, top: `${(Y(dialed[hover]) / H) * 100}%` }} />
        )}
        {marks.map((i) => (
          <span key={i} className="absolute bottom-3 -translate-x-1/2 whitespace-nowrap font-mono text-[10.5px] text-white/65" style={{ left: `clamp(28px, ${(X(i) / W) * 100}%, calc(100% - 28px))` }}>
            {label(days[i].date)}
          </span>
        ))}
        <div className="absolute inset-0 flex">
          {days.map((d, i) => (
            <div key={d.date} className="h-full flex-1" onMouseEnter={() => setHover(i)} />
          ))}
        </div>
        {h && hover !== null && (
          <div className="pointer-events-none absolute -top-2 z-20 min-w-[150px] -translate-x-1/2 rounded-2xl bg-zinc-950/90 px-3 py-2 text-xs text-white shadow-xl backdrop-blur" style={{ left: `clamp(80px, ${(X(hover) / W) * 100}%, calc(100% - 80px))` }}>
            <div className="mb-1 text-white/55">{label(h.date)}</div>
            {[["Dialed", h.dialed], ["Picked up", h.connected], ["Booked", h.booked]].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 leading-5"><span className="text-white/60">{k}</span><b className="font-mono font-medium">{v}</b></div>
            ))}
          </div>
        )}
      </div>
    </BentoCard>
  );
}

/* ── Reach gauge ─────────────────────────────────────────────────────────────── */

export function ReachGauge({ data }: { data: Analytics }) {
  const o = data.outcomes;
  const total = Object.values(o).reduce((a, b) => a + b, 0) || 1;
  const vm = (o.voicemail ?? 0) + (o.screened ?? 0);
  const none = (o.no_answer ?? 0) + (o.failed ?? 0) + (o.in_progress ?? 0);
  const person = Math.max(0, total - vm - none);
  const parts = [
    { key: "person", label: "Reached a person", n: person, color: ORANGE },
    { key: "vm", label: "Voicemail / screener", n: vm, color: "rgba(255,255,255,.75)" },
    { key: "none", label: "No answer", n: none, color: "rgba(255,255,255,.2)" },
  ];
  const n = 56;
  const ticks = Array.from({ length: n + 1 }, (_, i) => {
    const f = i / n, a = Math.PI + f * Math.PI;
    const color = f <= person / total ? parts[0].color : f <= (person + vm) / total ? parts[1].color : parts[2].color;
    const r1 = 136, r2 = i % 7 === 0 ? 112 : 118;
    return { x1: r1 * Math.cos(a), y1: r1 * Math.sin(a), x2: r2 * Math.cos(a), y2: r2 * Math.sin(a), color };
  });
  return (
    <BentoCard tone="dark" className="col-span-12 h-[380px] sm:col-span-6 lg:col-span-4">
      <div className="flex items-center justify-between">
        <Ttl>Who picked up</Ttl>
        <Sub dark>{total.toLocaleString()} calls</Sub>
      </div>
      <svg viewBox="-150 -150 300 168" className="mx-auto mt-3 w-full max-w-[290px]" aria-hidden>
        {ticks.map((t, i) => (
          <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke={t.color} strokeWidth={3.2} strokeLinecap="round" />
        ))}
        <text y={-22} textAnchor="middle" fontWeight={200} fontSize={52} fill="#fff" letterSpacing={-2}>
          {pct(person, total)}
          <tspan fontSize={17} dy={-24} fill="rgba(255,255,255,.56)">%</tspan>
        </text>
        <text y={0} textAnchor="middle" fontSize={12} fontWeight={500} fill="rgba(255,255,255,.45)">reached a real person</text>
      </svg>
      <div className="mt-auto">
        {parts.map((p, i) => (
          <div key={p.key} className={cn("flex h-8 items-center gap-3", i && "border-t border-white/10")}>
            <i className="h-2 w-2 rounded-full" style={{ background: p.color }} />
            <span className="flex-1 truncate text-[13px] font-medium">{p.label}</span>
            <span className="w-11 text-right font-mono text-xs text-white/45">{pct(p.n, total)}%</span>
            <span className="w-14 text-right font-mono text-[13px]">{p.n.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </BentoCard>
  );
}

/* ── KPI tiles ───────────────────────────────────────────────────────────────── */

export function KpiTiles({ data }: { data: Analytics }) {
  const f = data.funnel;
  const o = data.outcomes;
  const total = Object.values(o).reduce((a, b) => a + b, 0);
  const person = Object.entries(o).reduce((a, [k, v]) => a + (NO_PERSON.has(k) ? 0 : v), 0);
  const perMeeting = f.booked ? Math.round(data.credits_used / f.booked) : null;
  const tile = "col-span-12 h-[168px] sm:col-span-6 lg:col-span-3";
  return (
    <>
      <BentoCard tone="dark" className={tile}>
        <div className="flex items-center justify-between"><Cap dark>Meetings booked</Cap><Sub dark>{pct(f.booked, person)}% of reached</Sub></div>
        <Big className="mt-auto text-[52px]" >
          <span style={{ color: ORANGE }}>{f.booked.toLocaleString()}</span>
        </Big>
        <Sub dark className="mt-2">{f.qualified.toLocaleString()} interested or better</Sub>
      </BentoCard>
      <BentoCard tone="light" className={tile}>
        <div className="flex items-center justify-between"><Cap>Avg call length</Cap><Sub>{Math.round(data.total_minutes).toLocaleString()} min total</Sub></div>
        <Big className="mt-3">{formatDuration(data.avg_talk_seconds)}</Big>
        <div className="mt-auto"><Ticks share={Math.min(1, data.avg_talk_seconds / 120)} /></div>
        <div className="mt-1 flex justify-between font-mono text-[10px] text-zinc-400"><span>0:00</span><span>2:00</span></div>
      </BentoCard>
      <BentoCard tone="light" className={tile}>
        <div className="flex items-center justify-between"><Cap>Conversations</Cap><Sub>30 sec or more</Sub></div>
        <div className="mt-3 flex items-baseline justify-between">
          <Big>{f.conversations.toLocaleString()}</Big>
          <span className="font-mono text-sm text-zinc-500">{pct(f.conversations, total)}% of calls</span>
        </div>
        <div className="mt-auto"><Ticks share={total ? f.conversations / total : 0} /></div>
      </BentoCard>
      <BentoCard tone="light" className={tile}>
        <div className="flex items-center justify-between"><Cap>Credits used</Cap><Sub>This period</Sub></div>
        <Big className="mt-3">{data.credits_used.toLocaleString()}</Big>
        <div className="mt-auto flex items-center justify-between border-t border-zinc-100 pt-3 text-[13px]">
          <span className="font-medium text-zinc-600">Per meeting booked</span>
          <span className="font-mono font-medium">{perMeeting !== null ? perMeeting.toLocaleString() : "—"}</span>
        </div>
      </BentoCard>
    </>
  );
}

/* ── Funnel ──────────────────────────────────────────────────────────────────── */

const STEPS: { key: keyof Funnel; label: string }[] = [
  { key: "dialed", label: "Dialed" },
  { key: "connected", label: "Picked up" },
  { key: "conversations", label: "Talked 30s+" },
  { key: "qualified", label: "Interested+" },
  { key: "booked", label: "Booked" },
];

export function FunnelCard({ funnel }: { funnel: Funnel }) {
  const top = funnel.dialed || 1;
  return (
    <BentoCard tone="light" className="col-span-12 h-[360px] lg:col-span-5">
      <Ttl>From dial to meeting</Ttl>
      <Sub className="mt-1">How many calls make it through each step</Sub>
      <ol className="mt-auto flex flex-col gap-4">
        {STEPS.map((s, i) => {
          const v = funnel[s.key];
          const prev = i ? funnel[STEPS[i - 1].key] : 0;
          return (
            <li key={s.key} className="grid grid-cols-[6.5rem_1fr_4.75rem] items-center gap-3">
              <span className="truncate text-[13px] font-medium text-zinc-700">{s.label}</span>
              <div className="h-2.5 overflow-hidden rounded-full bg-zinc-100">
                <div className={cn("h-full rounded-full transition-all duration-700", s.key === "booked" ? "bg-emerald-600" : "brand-gradient")} style={{ width: `${Math.max(v ? 2 : 0, (v / top) * 100)}%` }} />
              </div>
              <span className="text-right">
                <span className="font-mono text-[13px] font-medium">{v.toLocaleString()}</span>
                {i > 0 && <span className="block font-mono text-[10.5px] text-zinc-400">{pct(v, prev)}% of prev</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </BentoCard>
  );
}

/* ── How calls ended ─────────────────────────────────────────────────────────── */

const SHADES = ["#dc4a1e", "#f19a77", "#fadccf"];

export function OutcomesCard({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = Object.entries(outcomes).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((a, [, n]) => a + n, 0) || 1;
  const head = rows.slice(0, 3);
  const name = (k: string) => (k === "in_progress" ? "In progress" : outcomeLabel(k));
  return (
    <BentoCard tone="light" className="col-span-12 h-[360px] sm:col-span-6 lg:col-span-4">
      <div className="flex items-center justify-between"><Ttl>How calls ended</Ttl><Sub>{rows.length} outcomes</Sub></div>
      <div className="mt-5 flex h-2.5 gap-[3px]">
        {head.map(([k, n], i) => (
          <div key={k} className="rounded-full" style={{ flex: `0 0 calc(${(n / total) * 100}% - 2px)`, background: SHADES[i] }} />
        ))}
        <div className="flex-1 rounded-full bg-zinc-100" />
      </div>
      <div className="mt-auto">
        {rows.slice(0, 5).map(([k, n], i) => (
          <div key={k} className={cn("flex h-10 items-center gap-3", i && "border-t border-zinc-100")}>
            <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: SHADES[i] ?? "#d4d4d8" }} />
            <span className="flex-1 truncate text-[13px] font-medium text-zinc-700">{name(k)}</span>
            <span className="w-10 text-right font-mono text-xs text-zinc-400">{pct(n, total)}%</span>
            <span className="w-14 text-right font-mono text-[13px] font-medium">{n.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </BentoCard>
  );
}

/* ── Best time to call ───────────────────────────────────────────────────────── */

export function BestTimeCard({ hours, best }: { hours: LocalHour[]; best: number[] }) {
  // The working day only: 8am–7pm, widened to any hour that actually had calls.
  const used = hours.filter((h) => h.calls > 0).map((h) => h.hour);
  const from = Math.min(8, ...used), to = Math.max(19, ...used);
  const span = hours.slice(from, to + 1);
  const max = Math.max(0.01, ...span.map((h) => h.rate));
  const [hover, setHover] = useState<LocalHour | null>(null);
  const shown = hover ?? (best.length ? [...best].map((b) => hours[b]).sort((a, b) => b.rate - a.rate)[0] : null);
  return (
    <BentoCard tone="dark" className="col-span-12 h-[360px] sm:col-span-6 lg:col-span-3">
      <Ttl>Best time to call</Ttl>
      <Big className="mt-4 text-[38px]">{shown ? `${shortHour(shown.hour)}m` : "—"}</Big>
      <div className="mt-2 flex gap-2 text-xs">
        <span className="font-mono font-semibold" style={{ color: ORANGE }}>{shown ? `${Math.round(shown.rate * 100)}% pick up` : "Not enough calls yet"}</span>
        {shown && <span className="font-medium text-white/45">{shown.calls} calls</span>}
      </div>
      <div className="mt-auto flex h-[130px] items-end gap-1" onMouseLeave={() => setHover(null)}>
        {span.map((h) => {
          const isBest = best.includes(h.hour);
          return (
            <div key={h.hour} className="flex h-full min-w-0 flex-1 flex-col items-center gap-1.5" onMouseEnter={() => setHover(h)}>
              <div className="relative w-full max-w-[14px] flex-1 overflow-hidden rounded-full bg-white/[.07]">
                <div className="absolute inset-x-0 bottom-0 rounded-full transition-all duration-700" style={{ height: `${(h.rate / max) * 100}%`, background: isBest ? ORANGE : "rgba(255,255,255,.55)" }} />
              </div>
              <span className={cn("h-3 font-mono text-[9px]", isBest ? "text-white" : "text-white/35")}>{h.hour % 3 === 0 ? shortHour(h.hour) : ""}</span>
            </div>
          );
        })}
      </div>
    </BentoCard>
  );
}

/* ── Prospect mood ───────────────────────────────────────────────────────────── */

export function MoodCard({ sentiment, className }: { sentiment: Analytics["sentiment"]; className?: string }) {
  const parts = [
    { label: "Positive", n: sentiment.positive, color: "#059669" },
    { label: "Neutral", n: sentiment.neutral, color: "#d4d4d8" },
    { label: "Negative", n: sentiment.negative, color: "#dc4a1e" },
  ];
  const total = parts.reduce((a, p) => a + p.n, 0);
  return (
    <BentoCard tone="light" className={className}>
      <div className="flex items-center justify-between"><Ttl>Prospect mood</Ttl><Sub>{total ? `${total} conversations read` : ""}</Sub></div>
      {total ? (
        <>
          <div className="mt-4 flex h-2.5 gap-[3px]">
            {parts.map((p) => p.n > 0 && <div key={p.label} className="rounded-full" style={{ flex: `${p.n} 0 0`, background: p.color }} />)}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-500">
            {parts.map((p) => (
              <span key={p.label} className="flex items-center gap-1.5">
                <i className="h-2 w-2 rounded-full" style={{ background: p.color }} />
                {p.label} <b className="font-mono font-medium text-zinc-900">{pct(p.n, total)}%</b>
              </span>
            ))}
          </div>
        </>
      ) : (
        <Sub className="mt-3">Appears once calls are analyzed.</Sub>
      )}
    </BentoCard>
  );
}
