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

/** How a call outcome or contact status reads in the app ("screened" → "Call screener · no answer"). */
const OUTCOME_LABEL: Record<string, string> = {
  completed: "Talked, no decision",
  callback: "Follow-up",
  screened: "Call screener · no answer",
  language_barrier: "Language barrier",
  hung_up: "Hung up",
  no_answer: "No answer",
  do_not_call: "Do not call",
};

export function outcomeLabel(s: string | null | undefined): string {
  return (s && OUTCOME_LABEL[s]) || humanize(s);
}

export const OUTCOME_TONE: Record<string, "green" | "blue" | "amber" | "red" | "gray" | "violet"> = {
  meeting_booked: "green",
  qualified: "blue",
  interested: "blue",
  transferred: "violet",
  callback: "amber",
  completed: "blue",
  not_qualified: "gray",
  not_interested: "gray",
  voicemail: "amber",
  screened: "amber",
  language_barrier: "violet",
  hung_up: "gray",
  no_answer: "amber",
  failed: "red",
};

export const CAMPAIGN_TONE = { draft: "gray", running: "green", paused: "amber", completed: "blue", cancelled: "red" } as const;

/** A plain-language line for an agent action in the transcript; null hides internal steps. */
export function toolLabel(tool: string | undefined, args: Record<string, unknown> | undefined): string | null {
  const a = args ?? {};
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  switch (tool) {
    case "check_availability":
    case "book_meeting":
      return "Checked the calendar";
    case "book_appointment":
    case "confirm_meeting":
      return "Booked the appointment" + (str(a.email) ? ` · ${str(a.email)}` : "");
    case "transfer_call":
      return "Transferred the call";
    case "voicemail":
      return a.action === "left_message" ? "Left a voicemail" : "Reached voicemail";
    case "call_screener":
      return a.action === "hang_up" ? "Call screener answered · hung up" : "Call screener answered · waited for the person";
    case "end_call":
      return a.reason === "silence" ? "Ended the call after silence" : "Ended the call" + (str(a.outcome) ? ` · ${humanize(str(a.outcome))}` : "");
    case "qualify_lead":
      return "Qualified the lead";
    case "log_qualification_answer":
      return str(a.question) ? `Noted: ${str(a.question)} — ${str(a.answer)}` : null;
    default:
      return null;
  }
}

/** +15419625730 → (541) 962-5730; anything else as stored. */
export function formatPhone(p: string | null | undefined): string {
  const d = (p || "").replace(/\D/g, "");
  const n = d.length === 11 && d.startsWith("1") ? d.slice(1) : d;
  return n.length === 10 ? `(${n.slice(0, 3)}) ${n.slice(3, 6)}-${n.slice(6)}` : p || "";
}
