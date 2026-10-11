export type MeetingStatus = "scheduled" | "completed" | "no_show" | "cancelled";

export type Meeting = {
  call_id: string;
  contact: { id: string; name: string; company: string; phone: string; email: string } | null;
  to_phone: string | null;
  prospect_email: string | null;
  meeting_time: string | null;
  meeting_link: string | null;
  agent_id: string | null;
  agent_name: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  call_type: string;
  summary: string | null;
  booked_at: string | null;
  follow_up_status: MeetingStatus;
  /** ISO start, when known: "set" in BlackSync, or "parsed" from what the agent agreed on the call. */
  start: string | null;
  start_source: "set" | "parsed" | null;
  duration_minutes: number;
  calendar_synced: boolean;
  calendar_error?: string;
};

export type GoogleStatus = { configured: boolean; connected: boolean; email: string | null; connected_at: string | null; can_manage: boolean };

export type BusyEvent = { id: string; title: string; start: string; end: string | null; link?: string };

/** "Tue, Oct 13 · 2:00 PM" in the viewer's time zone. */
export function formatStart(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} · ${d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
}

export type MeetingsResponse = {
  items: Meeting[];
  total: number;
  stats: {
    this_week: number;
    this_month: number;
    by_status: Record<MeetingStatus, number>;
    show_rate: number | null;
  };
};

export const MEETING_STATUS: { value: MeetingStatus; label: string; tone: "blue" | "green" | "amber" | "gray" }[] = [
  { value: "scheduled", label: "Scheduled", tone: "blue" },
  { value: "completed", label: "Completed", tone: "green" },
  { value: "no_show", label: "No-show", tone: "amber" },
  { value: "cancelled", label: "Cancelled", tone: "gray" },
];
