import clsx, { type ClassValue } from "clsx";

export const cn = (...v: ClassValue[]) => clsx(v);

/** Parse backend timestamps; SQLite drops the timezone, and they're always UTC. */
export function parseDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  const hasTz = /([zZ]|[+-]\d\d:?\d\d)$/.test(s);
  const d = new Date(hasTz ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgo(s: string | null | undefined): string {
  const d = parseDate(s);
  if (!d) return "—";
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  if (sec < 86400 * 7) return `${Math.floor(sec / 86400)}d ago`;
  return d.toLocaleDateString();
}

export function formatDateTime(s: string | null | undefined): string {
  const d = parseDate(s);
  return d ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
}

/** Credits with up to two decimals: 148.92, 1.1, 0.08. */
export function formatCredits(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function formatDuration(sec: number | null | undefined): string {
  if (!sec) return "0:00";
  const m = Math.floor(sec / 60);
  return `${m}:${String(sec % 60).padStart(2, "0")}`;
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const OUTCOME_TONE: Record<string, "green" | "blue" | "amber" | "red" | "gray" | "violet"> = {
  meeting_booked: "green",
  qualified: "blue",
  interested: "blue",
  transferred: "violet",
  callback: "amber",
  completed: "gray",
  not_qualified: "gray",
  not_interested: "gray",
  voicemail: "amber",
  no_answer: "amber",
  failed: "red",
};

export const CAMPAIGN_TONE = { draft: "gray", running: "green", paused: "amber", completed: "blue", cancelled: "red" } as const;
