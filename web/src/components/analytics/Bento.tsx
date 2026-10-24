"use client";

import { useState, type ReactNode } from "react";
import { cn, formatDuration, outcomeLabel } from "@/lib/utils";
import type { LocalHour } from "./hours";
import { shortHour } from "./hours";
import { pct, type Analytics, type Funnel } from "./types";

/* A dark bento dashboard for call analytics: gradient cards, tick gauges and capsule bars.
   Charts are plain SVG; everything sizes with its card. */

const ACC = "#E8FF1F";
const NO_PERSON = new Set(["voicemail", "no_answer", "failed", "screened", "in_progress"]);

type Gradient = { top: string; base: string; bottom: string; core: string };
export const GR: Record<string, Gradient> = {
  brand: { top: "#ffc2a1", base: "#f05a1f", bottom: "#ff8a57", core: "#5a1a04" },
  graph: { top: "#9a9aa8", base: "#3a3a44", bottom: "#55555f", core: "#060608" },
  pink: { top: "#ffb3d6", base: "#ff2a85", bottom: "#ff6aa8", core: "#3a031c" },
  copper: { top: "#f6bf96", base: "#c2683a", bottom: "#dc8a5c", core: "#1d0b05" },
  green: { top: "#a6e8c8", base: "#36956f", bottom: "#58b58c", core: "#061d15" },
  lime: { top: "#f4ffb8", base: "#a3c400", bottom: "#c9e03a", core: "#121700" },
};

/** A rounded card with a vertical gradient and a dark blurred core (or frosted glass). */
export function BentoCard({ g, glass, className, children }: { g?: Gradient; glass?: boolean; className?: string; children: ReactNode }) {
  return (
    <section
      className={cn(
        "relative min-w-0 overflow-hidden rounded-[28px] text-white",
        glass && "border border-white/10 bg-white/[0.06] backdrop-blur-xl",
        className,
      )}
    >
      {g && (
        <>
          <div className="absolute inset-0" style={{ background: `linear-gradient(180deg,${g.top} 0%,${g.base} 36%,${g.base} 74%,${g.bottom} 100%)` }} />
          <div className="absolute inset-x-[10%] bottom-[-6%] top-[16%] rounded-[90px] blur-[60px]" style={{ background: g.core }} />
          <div className="pointer-events-none absolute inset-0 z-10 rounded-[inherit] shadow-[inset_0_1px_0_rgba(255,255,255,.2),inset_0_0_0_1px_rgba(255,255,255,.06)]" />
        </>
      )}
      <div className="relative z-[2] flex h-full flex-col p-5 sm:p-6">{children}</div>
    </section>
  );
}

const Cap = ({ children }: { children: ReactNode }) => <div className="text-[11px] font-semibold uppercase tracking-[.08em] text-white/55">{children}</div>;
const Ttl = ({ children }: { children: ReactNode }) => <div className="text-lg font-semibold tracking-tight">{children}</div>;
const Muted = ({ children, className }: { children: ReactNode; className?: string }) => <div className={cn("text-xs font-medium text-white/45", className)}>{children}</div>;
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

/** Tick marks filled up to `share` (0–1): runway / progress bars. */
function Ticks({ share, n = 36, color = ACC }: { share: number; n?: number; color?: string }) {
  return (
    <svg viewBox={`0 0 ${n * 6} 20`} preserveAspectRatio="none" className="h-5 w-full" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <line key={i} x1={i * 6 + 3} x2={i * 6 + 3} y1={i % 6 === 0 ? 2 : 8} y2={20} stroke={i / (n - 1) <= share && share > 0 ? color : "rgba(255,255,255,.28)"} strokeWidth={1.6} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
}

/* ── Calls trend (hero) ─────────────────────────────────────────────────────── */

export function CallsHero({ data }: { data: Analytics }) {
  const f = data.funnel;
  const days = data.by_day ?? [];
  const [hover, setHover] = useState<number | null>(null);
  const W = 1000, H = 230, top = 24, bot = 30;
  const max = Math.max(1, ...days.map((d) => d.dialed));
  const X = (i: number) => (days.length < 2 ? W / 2 : (i / (days.length - 1)) * W);
  const Y = (v: number) => H - bot - (v / max) * (H - top - bot);
  const area = (key: "dialed" | "connected") => {
    const P = days.map((d, i) => [X(i), Y(d[key])] as [number, number]);
    return P.length ? `${smooth(P)}L${W},${H - bot}L0,${H - bot}Z` : "";
  };
  const label = (iso: string) => new Date(iso + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const marks = days.length > 2 ? [0, Math.round((days.length - 1) / 2), days.length - 1] : days.map((_, i) => i);
  const h = hover !== null ? days[hover] : null;
  return (
    <BentoCard g={GR.brand} className="col-span-12 h-[400px] lg:col-span-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <Ttl>Calls</Ttl>
        <div className="flex gap-4 text-xs font-medium text-white/70">
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-white" />Dialed</span>
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#3a1205] ring-1 ring-white/40" />Picked up</span>
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: ACC }} />Booked</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-1">
        <Big className="text-[64px]">{f.dialed.toLocaleString()}</Big>
        <div className="pb-1.5">
          <div className="font-mono text-[12.5px] font-semibold" style={{ color: ACC }}>↑ {pct(f.connected, f.dialed)}% picked up</div>
          <Muted className="mt-0.5">{data.total_minutes.toLocaleString()} minutes of talk time</Muted>
        </div>
      </div>
      <div className="absolute inset-x-0 bottom-0 h-[170px] sm:h-[230px]" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden>
          <path d={area("dialed")} fill="#fff" opacity={0.92} />
          <path d={area("connected")} fill="#3a1205" opacity={0.6} />
          {hover !== null && <line x1={X(hover)} x2={X(hover)} y1={top - 6} y2={H - bot} stroke="#000" strokeOpacity={0.5} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
        </svg>
        {/* booked meetings as lime dots on the dialed line */}
        {days.map((d, i) =>
          d.booked > 0 ? (
            <span key={d.date} className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-black/40" style={{ left: `${(X(i) / W) * 100}%`, top: `${(Y(d.dialed) / H) * 100}%`, background: ACC }} />
          ) : null,
        )}
        {marks.map((i) => (
          <span key={i} className="absolute bottom-2 -translate-x-1/2 whitespace-nowrap rounded-full bg-black px-2.5 py-1 font-mono text-[10.5px] text-white/70" style={{ left: `clamp(40px, ${(X(i) / W) * 100}%, calc(100% - 40px))` }}>
            {label(days[i].date)}
          </span>
        ))}
        <div className="absolute inset-0 flex">
          {days.map((d, i) => (
            <div key={d.date} className="h-full flex-1" onMouseEnter={() => setHover(i)} />
          ))}
        </div>
        {h && hover !== null && (
          <div className="pointer-events-none absolute top-0 z-20 min-w-[150px] -translate-x-1/2 rounded-2xl border border-white/10 bg-black/85 px-3 py-2 text-xs backdrop-blur-xl" style={{ left: `clamp(80px, ${(X(hover) / W) * 100}%, calc(100% - 80px))` }}>
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
    { key: "person", label: "Reached a person", n: person, color: "#ffffff" },
    { key: "vm", label: "Voicemail / screener", n: vm, color: "#FFB37A" },
    { key: "none", label: "No answer", n: none, color: "rgba(255,255,255,.3)" },
  ];
  const n = 56;
  const ticks = Array.from({ length: n + 1 }, (_, i) => {
    const f = i / n, a = Math.PI + f * Math.PI;
    const color = f <= person / total ? parts[0].color : f <= (person + vm) / total ? parts[1].color : parts[2].color;
    const r1 = 136, r2 = i % 7 === 0 ? 112 : 118;
    return { x1: r1 * Math.cos(a), y1: r1 * Math.sin(a), x2: r2 * Math.cos(a), y2: r2 * Math.sin(a), color };
  });
  return (
    <BentoCard g={GR.graph} className="col-span-12 h-[400px] sm:col-span-6 lg:col-span-4">
      <div className="flex items-center justify-between">
        <Ttl>Who picked up</Ttl>
        <span className="rounded-full bg-white/10 px-2.5 py-1 font-mono text-[11px] font-semibold">{total.toLocaleString()} calls</span>
      </div>
      <svg viewBox="-150 -150 300 168" className="mx-auto mt-4 w-full max-w-[300px]" aria-hidden>
        {ticks.map((t, i) => (
          <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke={t.color} strokeWidth={3.2} strokeLinecap="round" />
        ))}
        <text y={-22} textAnchor="middle" fontWeight={200} fontSize={52} fill="#fff" letterSpacing={-2}>
          {pct(person, total)}
          <tspan fontSize={17} dy={-24} fill="rgba(255,255,255,.56)">%</tspan>
        </text>
        <text y={0} textAnchor="middle" fontSize={12} fontWeight={500} fill="rgba(255,255,255,.4)">reached a person</text>
      </svg>
      <div className="mt-auto">
        {parts.map((p, i) => (
          <div key={p.key} className={cn("flex h-8 items-center gap-3", i && "border-t border-white/10")}>
            <i className="h-2 w-2 rounded-full" style={{ background: p.color }} />
            <span className="flex-1 truncate text-[13px] font-semibold">{p.label}</span>
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
  return (
    <>
      <BentoCard g={GR.lime} className="col-span-12 h-[176px] sm:col-span-6 lg:col-span-3">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-[.08em] text-black/55">Meetings booked</div>
          <span className="whitespace-nowrap rounded-full bg-black/85 px-2.5 py-1 font-mono text-[11px] font-semibold">{pct(f.booked, person)}% of reached</span>
        </div>
        <div className="mt-auto flex items-center gap-2">
          <svg width="30" height="36" viewBox="0 0 34 40" aria-hidden><path d="M17 37V5M5 17L17 5l12 12" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          <Big className="text-[52px]">{f.booked.toLocaleString()}</Big>
        </div>
        <div className="mt-1 text-[11.5px] font-medium text-white/70">{f.qualified.toLocaleString()} interested or better</div>
      </BentoCard>
      <BentoCard glass className="col-span-12 h-[176px] sm:col-span-6 lg:col-span-3">
        <div className="flex items-center justify-between"><Cap>Avg call length</Cap><Muted>Talk time</Muted></div>
        <div className="mt-3 flex items-baseline justify-between">
          <Big>{formatDuration(data.avg_talk_seconds)}</Big>
          <span className="font-mono text-xl font-medium">{Math.round(data.total_minutes).toLocaleString()}<span className="text-xs text-white/45"> min</span></span>
        </div>
        <div className="mt-auto"><Ticks share={Math.min(1, data.avg_talk_seconds / 120)} /></div>
        <Muted className="mt-1 text-right font-mono text-[10px]">2 min</Muted>
      </BentoCard>
      <BentoCard glass className="col-span-12 h-[176px] sm:col-span-6 lg:col-span-3">
        <div className="flex items-center justify-between"><Cap>Conversations</Cap><Muted>30 sec or more</Muted></div>
        <div className="mt-3 flex items-baseline justify-between">
          <Big>{f.conversations.toLocaleString()}</Big>
          <span className="font-mono text-xl font-medium">{pct(f.conversations, total)}<span className="text-xs text-white/45">% of calls</span></span>
        </div>
        <div className="mt-auto"><Ticks share={total ? f.conversations / total : 0} /></div>
      </BentoCard>
      <BentoCard glass className="col-span-12 h-[176px] sm:col-span-6 lg:col-span-3">
        <div className="flex items-center justify-between"><Cap>Credits used</Cap><Muted>This period</Muted></div>
        <Big className="mt-3">{data.credits_used.toLocaleString()}</Big>
        <div className="mt-auto flex items-center justify-between border-t border-white/10 pt-3 text-[13px]">
          <span className="font-semibold">Per meeting</span>
          <span className="font-mono">{perMeeting !== null ? perMeeting.toLocaleString() : "—"}</span>
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
    <BentoCard g={GR.pink} className="col-span-12 h-[340px] lg:col-span-5">
      <div className="flex items-start justify-between">
        <div>
          <Ttl>From dial to meeting</Ttl>
          <Muted className="mt-1">How many calls make it through each step</Muted>
        </div>
      </div>
      <ol className="mt-auto flex flex-col gap-3">
        {STEPS.map((s, i) => {
          const v = funnel[s.key];
          const prev = i ? funnel[STEPS[i - 1].key] : 0;
          return (
            <li key={s.key} className="grid grid-cols-[6.5rem_1fr_4.5rem] items-center gap-3">
              <span className="truncate text-[13px] font-semibold">{s.label}</span>
              <div className="h-[18px] overflow-hidden rounded-full bg-black/30">
                <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(v ? 3 : 0, (v / top) * 100)}%`, background: s.key === "booked" ? ACC : "#fff" }} />
              </div>
              <span className="text-right font-mono text-[13px]">
                {v.toLocaleString()}
                {i > 0 && <span className="block text-[10.5px] text-white/55">{pct(v, prev)}% of prev</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </BentoCard>
  );
}

/* ── How calls ended ─────────────────────────────────────────────────────────── */

export function OutcomesCard({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = Object.entries(outcomes).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((a, [, n]) => a + n, 0) || 1;
  const head = rows.slice(0, 3);
  const shades = [0.95, 0.6, 0.32];
  return (
    <BentoCard g={GR.copper} className="col-span-12 h-[340px] sm:col-span-6 lg:col-span-4">
      <div className="flex items-center justify-between"><Ttl>How calls ended</Ttl><Muted>{rows.length} outcomes</Muted></div>
      <div className="mt-4 flex h-1.5 gap-[3px]">
        {head.map(([k, n], i) => (
          <div key={k} className="rounded-full" style={{ flex: `0 0 calc(${(n / total) * 100}% - 2px)`, background: `rgba(255,255,255,${shades[i]})` }} />
        ))}
        <div className="flex-1 rounded-full bg-white/15" />
      </div>
      <div className="mt-2 flex gap-3 font-mono text-[11px] text-white/55">
        {head.map(([k, n]) => (
          <span key={k} className="truncate">{outcomeLabel(k).split(" ")[0]} {pct(n, total)}%</span>
        ))}
      </div>
      <div className="mt-auto">
        {rows.slice(0, 6).map(([k, n], i) => (
          <div key={k} className={cn("flex h-[34px] items-center gap-3", i && "border-t border-white/10")}>
            <span className="flex-1 truncate text-[13px] font-semibold">{k === "in_progress" ? "In progress" : outcomeLabel(k)}</span>
            <span className="w-10 text-right font-mono text-xs text-white/55">{pct(n, total)}%</span>
            <span className="w-14 text-right font-mono text-[13px]">{n.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </BentoCard>
  );
}

/* ── Best time to call ───────────────────────────────────────────────────────── */

export function BestTimeCard({ hours, best }: { hours: LocalHour[]; best: number[] }) {
  // The working day: from the first to the last hour anyone was called (at least 8am–7pm).
  const used = hours.filter((h) => h.calls > 0).map((h) => h.hour);
  const from = Math.min(8, ...used), to = Math.max(19, ...used);
  const span = hours.slice(from, to + 1);
  const max = Math.max(0.01, ...span.map((h) => h.rate));
  const top = best.length ? hours[best[best.length - 1]] : null;
  const [hover, setHover] = useState<LocalHour | null>(null);
  const shown = hover ?? (best.length ? hours[best[0]] : null);
  return (
    <BentoCard g={GR.green} className="col-span-12 h-[340px] sm:col-span-6 lg:col-span-3">
      <Ttl>Best time to call</Ttl>
      <Big className="mt-3 text-[34px]">{shown ? `${shortHour(shown.hour)}m` : "—"}</Big>
      <div className="mt-1.5 flex gap-2 text-xs">
        <span className="font-mono font-semibold" style={{ color: ACC }}>{shown ? `${Math.round(shown.rate * 100)}% pick up` : ""}</span>
        <span className="font-medium text-white/50">{shown ? `${shown.calls} calls` : top ? "" : "Not enough calls yet"}</span>
      </div>
      <div className="mt-auto flex h-[150px] items-end gap-[3px]" onMouseLeave={() => setHover(null)}>
        {span.map((h) => {
          const isBest = best.includes(h.hour);
          return (
            <div key={h.hour} className="flex h-full min-w-0 flex-1 flex-col items-center gap-1" onMouseEnter={() => setHover(h)}>
              <div className="relative w-full max-w-[18px] flex-1 overflow-hidden rounded-full bg-black/25">
                <div className="absolute inset-x-0 bottom-0 rounded-full transition-all duration-700" style={{ height: `${(h.rate / max) * 100}%`, background: isBest ? ACC : "#fff" }} />
              </div>
              <span className={cn("font-mono text-[9px]", isBest ? "text-white" : "text-white/40")}>{h.hour % 3 === 0 ? shortHour(h.hour) : ""}</span>
            </div>
          );
        })}
      </div>
    </BentoCard>
  );
}
