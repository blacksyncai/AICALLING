export type LoadStatus = "active" | "at_risk" | "late" | "unresponsive" | "delivered" | "cancelled";

export interface Stop {
  city: string;
  state: string;
  start: string | null;
  end: string | null;
}

export interface Load {
  id: string;
  load_id: string;
  driver_name: string;
  driver_phone: string;
  pickup: Stop;
  delivery: Stop;
  shipper_name: string;
  broker_reference: string;
  commodity: string;
  trailer: string;
  notes: string;
  status: LoadStatus;
  sms_only: boolean;
  do_not_call: boolean;
  last_location: string;
  loaded: "yes" | "no" | "unknown";
  last_eta: string | null;
  last_eta_text: string;
  delay_reason: string;
  last_check_at: string | null;
  next_check_at: string | null;
  next_check_kind: string;
  round: string | null;
  delivered_at: string | null;
  created_at: string | null;
}

export interface Board {
  items: Load[];
  counts: Partial<Record<LoadStatus, number>>;
  open_alerts: number;
}

export interface Check {
  id: string;
  kind: string;
  channel: "call" | "sms" | "manual";
  outcome: string;
  attempted_at: string | null;
  call_id: string | null;
  location: string;
  loaded: string;
  eta: string | null;
  eta_text: string;
  delay_reason: string;
  notes: string;
  message: string;
  confidence: string;
  needs_review: boolean;
  duration_sec: number | null;
  entered_by: string;
  transcript?: { role: string; text: string }[];
  has_recording?: boolean;
}

export interface Alert {
  id: string;
  load: string;
  load_id: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  kind: string;
  message: string;
  sent_at: string | null;
  delivered_via: string[];
  acknowledged_at: string | null;
  acknowledged_by: string;
}

export interface LoadDetail {
  load: Load;
  timeline: Check[];
  alerts: Alert[];
}

export interface Settings {
  broker_name: string;
  agent_name: string;
  agent_id: string | null;
  caller_number: string;
  timezone: string;
  check_interval_hours: number;
  quiet_start_hour: number;
  quiet_end_hour: number;
  call_late_loads_in_quiet_hours: boolean;
  sms_only: boolean;
  alert_emails: string[];
  alert_phone: string;
  plan: string;
  plans: Record<string, { label: string; loads_per_week: number | null }>;
  plan_limit: number | null;
  paused: boolean;
  texting_connected: boolean;
  sms_webhook_url: string;
}

export interface Stats {
  week_start: string;
  week_end: string;
  loads_tracked: number;
  loads_added: number;
  loads_delivered: number;
  check_ins: number;
  calls: number;
  calls_answered: number;
  texts_sent: number;
  text_replies: number;
  attempts: number;
  answer_rate: number | null;
  late_flagged: number;
  late_flagged_early: number;
  unresponsive: number;
  at_risk: number;
  hours_saved: number;
  plan: string;
  plan_limit: number | null;
}

export const STATUS: Record<LoadStatus, { label: string; tone: "green" | "amber" | "red" | "gray" | "blue"; dot: string }> = {
  late: { label: "Late", tone: "red", dot: "bg-red-500" },
  at_risk: { label: "At risk", tone: "amber", dot: "bg-amber-500" },
  unresponsive: { label: "Unresponsive", tone: "red", dot: "bg-red-400" },
  active: { label: "On time", tone: "green", dot: "bg-emerald-500" },
  delivered: { label: "Delivered", tone: "blue", dot: "bg-blue-500" },
  cancelled: { label: "Cancelled", tone: "gray", dot: "bg-zinc-400" },
};

export const ALERT_LABEL: Record<string, string> = {
  late: "Late",
  at_risk: "At risk",
  unresponsive: "Unresponsive",
  driver_requested_human: "Driver wants a call",
  dnc: "Driver opted out",
  needs_review: "Check the answer",
};

export const CHECK_KIND: Record<string, string> = {
  pickup: "Pickup check",
  en_route: "En-route check",
  pre_delivery: "Pre-delivery check",
  delivery: "Delivery check",
  manual: "Check-in",
  welcome: "Welcome text",
};

export const OUTCOME: Record<string, string> = {
  dialing: "Calling…",
  answered: "Answered",
  no_answer: "No answer",
  voicemail: "Voicemail left",
  failed: "Couldn't reach",
  sms_sent: "Text sent",
  sms_reply: "Driver replied",
  manual: "Entered by your team",
};

/** "Thu 2:30 PM" in the viewer's zone. */
export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
}

export function windowText(s: Stop): string {
  if (!s.start) return "—";
  const start = new Date(s.start);
  const day = start.toLocaleDateString(undefined, { weekday: "short", month: "numeric", day: "numeric" });
  const t = (d: Date) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return s.end ? `${day} ${t(start)}–${t(new Date(s.end))}` : `${day} ${t(start)}`;
}

export function etaText(l: Pick<Load, "last_eta" | "last_eta_text">): string {
  if (l.last_eta) return when(l.last_eta);
  return l.last_eta_text || "—";
}
