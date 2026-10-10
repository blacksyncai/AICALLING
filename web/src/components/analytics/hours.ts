import type { HourRow } from "./types";

export type LocalHour = { hour: number; calls: number; connected: number; rate: number };

/** The API buckets by UTC hour; shift each bucket into the viewer's local time. */
export function toLocalHours(rows: HourRow[]): LocalHour[] {
  const shift = -new Date().getTimezoneOffset(); // minutes ahead of UTC
  const out: LocalHour[] = Array.from({ length: 24 }, (_, hour) => ({ hour, calls: 0, connected: 0, rate: 0 }));
  for (const r of rows) {
    const local = Math.floor((((r.hour * 60 + shift) % 1440) + 1440) % 1440 / 60);
    out[local].calls += r.calls;
    out[local].connected += r.connected;
  }
  for (const h of out) h.rate = h.calls ? h.connected / h.calls : 0;
  return out;
}

/** Top hours by connect rate. Hours with very few calls are ignored when there's enough data. */
export function bestHours(hours: LocalHour[], n = 3): number[] {
  const withCalls = hours.filter((h) => h.calls > 0);
  const total = withCalls.reduce((a, h) => a + h.calls, 0);
  const minCalls = total >= 60 ? 5 : total >= 20 ? 2 : 1;
  const pool = withCalls.filter((h) => h.calls >= minCalls && h.connected > 0);
  return pool
    .sort((a, b) => b.rate - a.rate || b.connected - a.connected)
    .slice(0, n)
    .map((h) => h.hour)
    .sort((a, b) => a - b);
}

function hourLabel(h: number, withSuffix = true) {
  const n = h % 12 === 0 ? 12 : h % 12;
  return withSuffix ? `${n}${h % 24 < 12 ? "am" : "pm"}` : String(n);
}

export function shortHour(h: number) {
  const n = h % 12 === 0 ? 12 : h % 12;
  return `${n}${h < 12 ? "a" : "p"}`;
}

/** "10–11am" or "11am–1pm". */
export function rangeLabel(start: number, end: number) {
  const sameHalf = start < 12 === end % 24 < 12 && end - start < 12;
  return sameHalf ? `${hourLabel(start, false)}–${hourLabel(end % 24)}` : `${hourLabel(start)}–${hourLabel(end % 24)}`;
}

/** Merge adjacent hours into ranges and join: "10–11am and 2–3pm". */
export function describeHours(hours: number[]): string {
  const ranges: [number, number][] = [];
  for (const h of hours) {
    const last = ranges[ranges.length - 1];
    if (last && last[1] === h) last[1] = h + 1;
    else ranges.push([h, h + 1]);
  }
  const labels = ranges.map(([s, e]) => rangeLabel(s, e));
  if (labels.length <= 1) return labels[0] ?? "";
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}
