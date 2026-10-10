/**
 * Pure helpers for the dashboard's AI Calling Activity heat map: metric labels,
 * range labels, and where clicking a day goes. No React/DOM, so they run under
 * plain Node (see activity-model.test.mjs).
 */

import type { ActivityMetric, ActivityRange } from "@/lib/types"

export type { ActivityMetric, ActivityRange }

export const METRICS: {
  value: ActivityMetric;
  label: string;
  unit: string;
  unitPlural: string;
  /** What a click on a day opens, in plain words. */
  opens: string;
}[] = [
  { value: "calls", label: "Total calls", unit: "call", unitPlural: "calls", opens: "this day's phone calls" },
  { value: "connected", label: "Connected conversations", unit: "connected call", unitPlural: "connected calls", opens: "this day's phone calls" },
  { value: "appointments", label: "Appointments booked", unit: "appointment", unitPlural: "appointments", opens: "this day's calls that booked a meeting" },
  { value: "transfers", label: "Warm transfers", unit: "warm transfer", unitPlural: "warm transfers", opens: "this day's calls marked transferred" },
  { value: "credits", label: "Credits used", unit: "credit", unitPlural: "credits", opens: "this day's phone calls" },
]

export const RANGES: { value: ActivityRange; label: string; short: string }[] = [
  { value: "30d", label: "last 30 days", short: "30 days" },
  { value: "90d", label: "last 90 days", short: "90 days" },
  { value: "12m", label: "last 12 months", short: "12 months" },
]

export const metricInfo = (m: ActivityMetric) => METRICS.find((x) => x.value === m) ?? METRICS[0]
export const rangeInfo = (r: ActivityRange) => RANGES.find((x) => x.value === r) ?? RANGES[2]

/** Outcome filter that genuinely matches the metric on the call-log page, if there is one. */
export const METRIC_OUTCOME: Partial<Record<ActivityMetric, string>> = {
  appointments: "meeting_booked",
  transfers: "transferred",
}

/**
 * The call-log link for one day. The activity map counts phone calls only, so the
 * list is narrowed to phone calls too; appointments and transfers add the matching
 * outcome filter. The organization always comes from the signed-in session.
 */
export function dayHref(date: string, metric: ActivityMetric, agentId?: string | null): string {
  const qs = new URLSearchParams({ date })
  if (agentId) qs.set("agent_id", agentId)
  const outcome = METRIC_OUTCOME[metric]
  if (outcome) qs.set("outcome", outcome)
  qs.set("call_type", "outbound")
  return "/calls?" + qs.toString()
}

/** "America/New_York" → "Eastern Time" (falls back to the IANA name). */
export function timeZoneLabel(tz: string, locale = "en-US"): string {
  try {
    const part = new Intl.DateTimeFormat(locale, { timeZone: tz, timeZoneName: "longGeneric" })
      .formatToParts(new Date())
      .find((p) => p.type === "timeZoneName")?.value
    return part || tz
  } catch {
    return tz
  }
}

/** "2026-10-03" → "Oct 3, 2026", read literally (no time-zone drift). */
export function formatDay(date: string, opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric" }, locale = "en-US"): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  if (!m) return date
  return new Intl.DateTimeFormat(locale, { ...opts, timeZone: "UTC" }).format(Date.UTC(+m[1], +m[2] - 1, +m[3]))
}
