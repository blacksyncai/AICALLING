"use client";

import { useState, type ReactNode } from "react";
import { cn, formatDuration, outcomeLabel } from "@/lib/utils";
import type { LocalHour } from "./hours";
import { shortHour } from "./hours";
import { pct, type Analytics, type Funnel } from "./types";

/* Call analytics, dark: charcoal cards on a near-black canvas, one burnt-orange hero, warm orange
   accents and a single yellow for the moments that matter. Charts are plain SVG. */

const ORANGE = "#ff8a57";
const GOLD = "#ffd84d";
const NO_PERSON = new Set(["voicemail", "no_answer", "failed", "screened", "in_progress"]);

// Film grain for the hero gradient (tiny inline SVG, tiled).
const NOISE =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 .55 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")";

type Glow = { top: string; base: string; bottom: string; core: string };
/** Gradient cards: light at the top edge, saturated in the middle, a dark blurred core underneath. */
const GLOW: Record<string, Glow> = {
  ember: { top: "#ffb48a", base: "#e0561f", bottom: "#ff8a57", core: "#3a1004" },
  graph: { top: "#9a9aa8", base: "#3a3a44", bottom: "#55555f", core: "#060608" },
  amber: { top: "#ffe2a6", base: "#e8900c", bottom: "#f6b23c", core: "#2b1600" },
  copper: { top: "#f6bf96", base: "#c2683a", bottom: "#dc8a5c", core: "#1d0b05" },
  green: { top: "#a6e8c8", base: "#2f8a68", bottom: "#4fa784", core: "#051a12" },
};

/** `glow` = a gradient card; without it the card is frosted glass over the lit canvas. */
export function BentoCard({ glow, grain, className, children }: { glow?: keyof typeof GLOW; grain?: boolean; className?: string; children: ReactNode }) {
  const g = glow ? GLOW[glow] : null;
  return (
    <section
      className={cn(
        "relative min-w-0 overflow-hidden rounded-[26px] text-white",
        g ? "shadow-[0_30px_60px_-34px_rgba(0,0,0,.8)]" : "border border-white/[.1] bg-white/[.055] backdrop-blur-2xl",
        className,
      )}
    >
      {g && (
        <>
          <div className="absolute inset-0" style={{ background: `linear-gradient(180deg,${g.top} 0%,${g.base} 36%,${g.base} 74%,${g.bottom} 100%)` }} />
          <div className="absolute inset-x-[10%] bottom-[-6%] top-[16%] rounded-[90px] blur-[60px]" style={{ background: g.core }} />
        </>
      )}
      {grain && <div className="pointer-events-none absolute inset-0 opacity-[.12] mix-blend-overlay" style={{ backgroundImage: NOISE }} />}
      <div className="pointer-events-none absolute inset-0 z-10 rounded-[inherit] shadow-[inset_0_1px_0_rgba(255,255,255,.2),inset_0_0_0_1px_rgba(255,255,255,.06)]" />
      <div className="relative z-[2] flex h-full flex-col p-5 sm:p-6">{children}</div>
    </section>
  );
}

const Ttl = ({ children }: { children: ReactNode }) => <div className="text-[15px] font-medium tracking-tight text-white/90">{children}</div>;
const Cap = ({ children }: { children: ReactNode }) => <div className="text-[10.5px] font-medium uppercase tracking-[.12em] text-white/45">{children}</div>;
const Sub = ({ children, className }: { children: ReactNode; className?: string }) => <div className={cn("text-xs text-white/40", className)}>{children}</div>;
const Big = ({ children, className, style }: { children: ReactNode; className?: string; style?: React.CSSProperties }) => (
  <div className={cn("text-[40px] font-extralight leading-none tracking-[-.045em] tabular-nums", className)} style={style}>{children}</div>
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

/** Thin tick marks filled up to `share` (0–1). */
function Ticks({ share, n = 40 }: { share: number; n?: number }) {
  return (
    <svg viewBox={`0 0 ${n * 6} 18`} preserveAspectRatio="none" className="h-[18px] w-full" aria-hidden>
      {Array.from({ length: n }, (_, i) => {
        const on = share > 0 && i / (n - 1) <= share;
        return <line key={i} x1={i * 6 + 3} x2={i * 6 + 3} y1={i % 8 === 0 ? 1 : 7} y2={18} stroke={on ? ORANGE : "rgba(255,255,255,.12)"} strokeWidth={1.5} strokeLinecap="round" vectorEffect="non-scaling-stroke" />;
      })}
    </svg>
  );
}

/* ── Calls trend (hero) ─────────────────────────────────────────────────────── */

export function CallsHero({ data }: { data: Analytics }) {
  const f = data.funnel;
  const days = data.by_day ?? [];
  const [hover, setHover] = useState<number | null>(null);
  const W = 1000, H = 210, top = 22, bot = 36;
  const avgWindow = days.length > 14 ? 7 : 3;
  const dialed = rolling(days.map((d) => d.dialed), avgWindow);
  const picked = rolling(days.map((d) => d.connected), avgWindow);
  const lo = Math.min(...picked, ...dialed), hi = Math.max(1, ...dialed);
  const floor = Math.max(0, lo - (hi - lo) * 0.6);
  const X = (i: number) => (days.length < 2 ? W / 2 : (i / (days.length - 1)) * W);
  const Y = (v: number) => H - bot - ((v - floor) / (hi - floor || 1)) * (H - top - bot);
  const line = (vals: number[]) => smooth(vals.map((v, i) => [X(i), Y(v)] as [number, number]));
  const fill = days.length ? `${line(dialed)}L${W},${H}L0,${H}Z` : "";
  // A few yellow accents: the days that booked the most meetings.
  const keys = days.map((d, i) => ({ i, b: d.booked })).filter((k) => k.b > 0).sort((a, b) => b.b - a.b).slice(0, 3).map((k) => k.i);
  const label = (iso: string) => new Date(iso + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const marks = days.length > 2 ? [0, Math.round((days.length - 1) / 2), days.length - 1] : days.map((_, i) => i);
  const h = hover !== null ? days[hover] : null;
  const stats = [
    [`${pct(f.connected, f.dialed)}%`, "picked up"],
    [Math.round(data.total_minutes).toLocaleString(), "min talk time"],
    [f.booked.toLocaleString(), f.booked === 1 ? "meeting" : "meetings"],
  ];
  return (
    <BentoCard glow="ember" grain className="col-span-12 h-[390px] lg:col-span-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <Ttl>Calls placed</Ttl>
        <div className="flex items-center gap-4 text-[11px] text-white/70">
          <span className="flex items-center gap-1.5"><i className="h-px w-4 bg-white" />Dialed</span>
          <span className="flex items-center gap-1.5"><i className="h-px w-4 bg-white/40" />Picked up</span>
          <span className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full" style={{ background: GOLD }} />Most meetings</span>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-end gap-x-8 gap-y-3">
        <Big className="text-[68px] font-thin">{f.dialed.toLocaleString()}</Big>
        <div className="flex gap-6 pb-2">
          {stats.map(([v, k]) => (
            <div key={k}>
              <div className="text-[15px] font-medium tabular-nums">{v}</div>
              <div className="mt-0.5 text-[11px] text-white/60">{k}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="absolute inset-x-0 bottom-0 h-[160px] sm:h-[210px]" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden>
          <defs>
            <linearGradient id="hero-fill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#fff" stopOpacity=".2" />
              <stop offset=".7" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={fill} fill="url(#hero-fill)" />
          <path d={line(picked)} fill="none" stroke="#fff" strokeOpacity={0.38} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
        </svg>
        {/* the dialed line carries a soft glow */}
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full [filter:drop-shadow(0_0_6px_rgba(255,255,255,.55))]" aria-hidden>
          <path d={line(dialed)} fill="none" stroke="#fff" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
          {hover !== null && <line x1={X(hover)} x2={X(hover)} y1={top - 8} y2={H - bot + 6} stroke="#fff" strokeOpacity={0.35} vectorEffect="non-scaling-stroke" />}
        </svg>
        {keys.map((i) => (
          <span key={i} className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${(X(i) / W) * 100}%`, top: `${(Y(dialed[i]) / H) * 100}%`, background: GOLD, boxShadow: `0 0 0 4px rgba(255,216,77,.18), 0 0 14px ${GOLD}` }} />
        ))}
        {hover !== null && (
          <span className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-[0_0_0_5px_rgba(255,255,255,.18),0_0_16px_#fff]" style={{ left: `${(X(hover) / W) * 100}%`, top: `${(Y(dialed[hover]) / H) * 100}%` }} />
        )}
        {marks.map((i) => (
          <span key={i} className="absolute bottom-3.5 -translate-x-1/2 whitespace-nowrap text-[10.5px] tabular-nums text-white/55" style={{ left: `clamp(30px, ${(X(i) / W) * 100}%, calc(100% - 30px))` }}>
            {label(days[i].date)}
          </span>
        ))}
        <div className="absolute inset-0 flex">
          {days.map((d, i) => (
            <div key={d.date} className="h-full flex-1" onMouseEnter={() => setHover(i)} />
          ))}
        </div>
        {h && hover !== null && (
          <div className="pointer-events-none absolute -top-3 z-20 min-w-[150px] -translate-x-1/2 rounded-xl border border-white/10 bg-[#141416]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur" style={{ left: `clamp(80px, ${(X(hover) / W) * 100}%, calc(100% - 80px))` }}>
            <div className="mb-1 text-white/45">{label(h.date)}</div>
            {[["Dialed", h.dialed], ["Picked up", h.connected], ["Booked", h.booked]].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 leading-5"><span className="text-white/55">{k}</span><b className="font-medium tabular-nums">{v}</b></div>
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
  const share = person / total;
  // A 270° ring, opening at the bottom.
  const R = 78, C = 2 * Math.PI * R, arc = C * 0.75;
  const parts = [
    { label: "Reached a person", n: person, color: ORANGE },
    { label: "Voicemail / screener", n: vm, color: "rgba(255,255,255,.55)" },
    { label: "No answer", n: none, color: "rgba(255,255,255,.18)" },
  ];
  return (
    <BentoCard glow="graph" className="col-span-12 h-[390px] sm:col-span-6 lg:col-span-4">
      <div className="flex items-center justify-between">
        <Ttl>Who picked up</Ttl>
        <Sub>{total.toLocaleString()} calls</Sub>
      </div>
      <div className="relative mx-auto mt-2 h-[190px] w-[190px]">
        <svg viewBox="0 0 200 200" className="h-full w-full rotate-[135deg]" aria-hidden>
          <defs>
            <linearGradient id="gauge" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#ffb38f" />
              <stop offset="1" stopColor="#e2541f" />
            </linearGradient>
          </defs>
          <circle cx="100" cy="100" r={R} fill="none" stroke="rgba(255,255,255,.07)" strokeWidth="12" strokeLinecap="round" strokeDasharray={`${arc} ${C}`} />
          <circle cx="100" cy="100" r={R} fill="none" stroke="url(#gauge)" strokeWidth="12" strokeLinecap="round" strokeDasharray={`${Math.max(0.001, arc * share)} ${C}`} className="[filter:drop-shadow(0_0_8px_rgba(255,138,87,.55))] transition-[stroke-dasharray] duration-1000" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center pt-1">
          <div className="text-[52px] font-thin leading-none tracking-[-.05em] tabular-nums">
            {pct(person, total)}
            <span className="ml-0.5 align-top text-lg text-white/45">%</span>
          </div>
          <div className="mt-1.5 text-[11px] text-white/45">reached a real person</div>
        </div>
      </div>
      <div className="mt-auto">
        {parts.map((p, i) => (
          <div key={p.label} className={cn("flex h-8 items-center gap-3", i && "border-t border-white/[.06]")}>
            <i className="h-1.5 w-1.5 rounded-full" style={{ background: p.color }} />
            <span className="flex-1 truncate text-[13px] text-white/80">{p.label}</span>
            <span className="w-10 text-right text-xs tabular-nums text-white/35">{pct(p.n, total)}%</span>
            <span className="w-14 text-right text-[13px] tabular-nums">{p.n.toLocaleString()}</span>
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
  const tile = "col-span-12 h-[164px] sm:col-span-6 lg:col-span-3";
  return (
    <>
      <BentoCard glow="amber" className={tile}>
        <div className="flex items-center justify-between"><Cap>Meetings booked</Cap><Sub>{pct(f.booked, person)}% of reached</Sub></div>
        <Big className="mt-auto text-[56px] font-thin" style={{ textShadow: "0 0 28px rgba(255,255,255,.55)" }}>
          {f.booked.toLocaleString()}
        </Big>
        <Sub className="mt-2">{f.qualified.toLocaleString()} interested or better</Sub>
      </BentoCard>
      <BentoCard className={tile}>
        <div className="flex items-center justify-between"><Cap>Avg call length</Cap><Sub>{Math.round(data.total_minutes).toLocaleString()} min total</Sub></div>
        <Big className="mt-3">{formatDuration(data.avg_talk_seconds)}</Big>
        <div className="mt-auto"><Ticks share={Math.min(1, data.avg_talk_seconds / 120)} /></div>
        <div className="mt-1.5 flex justify-between text-[10px] tabular-nums text-white/30"><span>0:00</span><span>2:00</span></div>
      </BentoCard>
      <BentoCard className={tile}>
        <div className="flex items-center justify-between"><Cap>Conversations</Cap><Sub>30 sec or more</Sub></div>
        <div className="mt-3 flex items-baseline justify-between">
          <Big>{f.conversations.toLocaleString()}</Big>
          <span className="text-sm tabular-nums text-white/45">{pct(f.conversations, total)}% of calls</span>
        </div>
        <div className="mt-auto"><Ticks share={total ? f.conversations / total : 0} /></div>
      </BentoCard>
      <BentoCard className={tile}>
        <div className="flex items-center justify-between"><Cap>Credits used</Cap><Sub>This period</Sub></div>
        <Big className="mt-3">{data.credits_used.toLocaleString()}</Big>
        <div className="mt-auto flex items-center justify-between border-t border-white/[.06] pt-3 text-[13px]">
          <span className="text-white/55">Per meeting booked</span>
          <span className="tabular-nums">{perMeeting !== null ? perMeeting.toLocaleString() : "—"}</span>
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
    <BentoCard glow="copper" className="col-span-12 h-[360px] lg:col-span-5">
      <Ttl>From dial to meeting</Ttl>
      <Sub className="mt-1">How many calls make it through each step</Sub>
      <ol className="mt-auto flex flex-col gap-[18px]">
        {STEPS.map((s, i) => {
          const v = funnel[s.key];
          const prev = i ? funnel[STEPS[i - 1].key] : 0;
          return (
            <li key={s.key} className="grid grid-cols-[6.25rem_1fr_4.5rem] items-center gap-4">
              <span className="truncate text-[13px] text-white/85">{s.label}</span>
              <div className="h-2 overflow-hidden rounded-full bg-black/25">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${Math.max(v ? 2.5 : 0, (v / top) * 100)}%`, background: s.key === "booked" ? GOLD : "linear-gradient(90deg,#ffe2cc,#fff)", boxShadow: s.key === "booked" ? `0 0 12px ${GOLD}` : "0 0 10px rgba(255,255,255,.35)" }}
                />
              </div>
              <span className="text-right">
                <span className="text-[13px] tabular-nums">{v.toLocaleString()}</span>
                {i > 0 && <span className="block text-[10.5px] tabular-nums text-white/55">{pct(v, prev)}% of prev</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </BentoCard>
  );
}

/* ── How calls ended ─────────────────────────────────────────────────────────── */

const SHADES = [ORANGE, "#ffc4a8", "rgba(255,255,255,.35)", "rgba(255,255,255,.2)", "rgba(255,255,255,.12)"];

export function OutcomesCard({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = Object.entries(outcomes).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((a, [, n]) => a + n, 0) || 1;
  const name = (k: string) => (k === "in_progress" ? "In progress" : outcomeLabel(k));
  return (
    <BentoCard className="col-span-12 h-[360px] sm:col-span-6 lg:col-span-4">
      <div className="flex items-center justify-between"><Ttl>How calls ended</Ttl><Sub>{rows.length} outcomes</Sub></div>
      <div className="mt-5 flex h-2 gap-[3px]">
        {rows.slice(0, 5).map(([k, n], i) => (
          <div key={k} className="min-w-[3px] rounded-full" style={{ flex: `${n} 0 0`, background: SHADES[i] }} />
        ))}
      </div>
      <div className="mt-auto">
        {rows.slice(0, 5).map(([k, n], i) => (
          <div key={k} className={cn("flex h-10 items-center gap-3", i && "border-t border-white/[.06]")}>
            <i className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: SHADES[i] }} />
            <span className="flex-1 truncate text-[13px] text-white/80">{name(k)}</span>
            <span className="w-10 text-right text-xs tabular-nums text-white/35">{pct(n, total)}%</span>
            <span className="w-14 text-right text-[13px] tabular-nums">{n.toLocaleString()}</span>
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
  const shown = hover ?? (best.length ? best.map((b) => hours[b]).sort((a, b) => b.rate - a.rate)[0] : null);
  return (
    <BentoCard glow="green" className="col-span-12 h-[360px] sm:col-span-6 lg:col-span-3">
      <Ttl>Best time to call</Ttl>
      <Big className="mt-4 text-[44px] font-thin">{shown ? `${shortHour(shown.hour)}m` : "—"}</Big>
      <div className="mt-2 flex gap-2 text-xs">
        <span style={{ color: GOLD }}>{shown ? `${Math.round(shown.rate * 100)}% pick up` : "Not enough calls yet"}</span>
        {shown && <span className="text-white/35">· {shown.calls} calls</span>}
      </div>
      <div className="mt-auto flex h-[132px] items-end gap-[5px]" onMouseLeave={() => setHover(null)}>
        {span.map((h) => {
          const isBest = best.includes(h.hour);
          const active = hover?.hour === h.hour;
          return (
            <div key={h.hour} className="flex h-full min-w-0 flex-1 flex-col items-center gap-1.5" onMouseEnter={() => setHover(h)}>
              <div className="relative w-full max-w-[10px] flex-1 overflow-hidden rounded-full bg-black/20">
                <div
                  className="absolute inset-x-0 bottom-0 rounded-full transition-all duration-700"
                  style={{
                    height: `${(h.rate / max) * 100}%`,
                    background: isBest || active ? GOLD : "rgba(255,255,255,.6)",
                    boxShadow: isBest ? `0 0 10px ${GOLD}` : undefined,
                  }}
                />
              </div>
              <span className={cn("h-3 text-[9px] tabular-nums", isBest ? "text-white" : "text-white/45")}>{h.hour % 3 === 0 ? shortHour(h.hour) : ""}</span>
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
    { label: "Positive", n: sentiment.positive, color: ORANGE },
    { label: "Neutral", n: sentiment.neutral, color: "rgba(255,255,255,.3)" },
    { label: "Negative", n: sentiment.negative, color: "rgba(255,255,255,.12)" },
  ];
  const total = parts.reduce((a, p) => a + p.n, 0);
  return (
    <BentoCard className={className}>
      <div className="flex items-center justify-between"><Ttl>Prospect mood</Ttl><Sub>{total ? `${total} conversations read` : ""}</Sub></div>
      {total ? (
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
          <div className="flex h-2 flex-1 gap-[3px]">
            {parts.map((p) => p.n > 0 && <div key={p.label} className="rounded-full" style={{ flex: `${p.n} 0 0`, background: p.color }} />)}
          </div>
          <div className="flex gap-5 text-xs text-white/45">
            {parts.map((p) => (
              <span key={p.label} className="flex items-center gap-1.5">
                <i className="h-1.5 w-1.5 rounded-full" style={{ background: p.color }} />
                {p.label} <b className="font-medium tabular-nums text-white/90">{pct(p.n, total)}%</b>
              </span>
            ))}
          </div>
        </div>
      ) : (
        <Sub className="mt-3">Appears once calls are analyzed.</Sub>
      )}
    </BentoCard>
  );
}
