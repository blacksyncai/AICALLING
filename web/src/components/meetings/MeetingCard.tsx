"use client";

import { Bot, CalendarCheck2, CalendarClock, Copy, Mail, Megaphone, PhoneCall, UserRound } from "lucide-react";
import Link from "next/link";
import { Badge, Button, Card, Select } from "@/components/ui";
import { useToast } from "@/components/toast";
import { cn, timeAgo } from "@/lib/utils";
import { MEETING_STATUS, formatStart, type Meeting, type MeetingStatus } from "./types";

export function MeetingCard({
  meeting: m,
  onStatus,
  onSetTime,
  saving,
}: {
  meeting: Meeting;
  onStatus: (s: MeetingStatus) => void;
  onSetTime?: () => void;
  saving?: boolean;
}) {
  const toast = useToast();
  const name = m.contact?.name || m.to_phone || (m.call_type === "web" ? "Browser test" : "Unknown contact");
  const email = m.prospect_email || m.contact?.email || null;
  const status = MEETING_STATUS.find((s) => s.value === m.follow_up_status) ?? MEETING_STATUS[0];

  async function copyLink() {
    if (!m.meeting_link) return;
    try {
      await navigator.clipboard.writeText(m.meeting_link);
      toast("Meeting link copied");
    } catch {
      toast("Couldn't copy the link", "error");
    }
  }

  return (
    <Card className={cn("flex flex-col gap-4 p-5", m.follow_up_status === "cancelled" && "opacity-70")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-semibold text-zinc-900">{name}</h3>
            <Badge tone={status.tone}>{status.label}</Badge>
          </div>
          {m.contact?.company && <p className="truncate text-sm text-zinc-500">{m.contact.company}</p>}
        </div>
        <button
          type="button"
          onClick={onSetTime}
          disabled={!onSetTime}
          title={m.start_source === "parsed" ? `Read from the call: "${m.meeting_time}". Click to confirm or change.` : onSetTime ? "Change the time" : undefined}
          className={cn(
            "flex items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm font-medium transition",
            m.start ? "bg-brand-50 text-brand-700" : "bg-amber-50 text-amber-800",
            onSetTime && "hover:ring-2 hover:ring-brand-200",
          )}
        >
          <CalendarClock className="h-4 w-4 shrink-0" />
          <span className="break-words">{m.start ? formatStart(m.start) : m.meeting_time || "Time not confirmed"}</span>
          {!m.start && onSetTime && <span className="text-xs font-semibold underline underline-offset-2">Set time</span>}
          {m.calendar_synced && <CalendarCheck2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" aria-label="On Google Calendar" />}
        </button>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5">
          <Bot className="h-3.5 w-3.5" />
          {m.agent_name ?? "Agent"}
        </span>
        {m.campaign_name && (
          <span className="flex min-w-0 items-center gap-1.5">
            <Megaphone className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{m.campaign_name}</span>
          </span>
        )}
        <span>Booked {timeAgo(m.booked_at)}</span>
        {email && (
          <a href={`mailto:${email}`} className="flex min-w-0 items-center gap-1.5 hover:text-brand-700">
            <Mail className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{email}</span>
          </a>
        )}
      </div>

      {m.summary && <p className="line-clamp-2 text-sm leading-relaxed text-zinc-700">{m.summary}</p>}

      <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-4">
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="sr-only sm:not-sr-only">Status</span>
          <Select
            className="h-8 w-36 text-xs"
            value={m.follow_up_status}
            disabled={saving}
            onChange={(e) => onStatus(e.target.value as MeetingStatus)}
            aria-label={`Meeting status for ${name}`}
          >
            {MEETING_STATUS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        </label>
        <div className="flex flex-1 flex-wrap justify-end gap-2">
          {m.meeting_link && (
            <Button size="sm" variant="ghost" onClick={copyLink}>
              <Copy className="h-3.5 w-3.5" /> Copy link
            </Button>
          )}
          {m.contact && (
            <Link href={`/contacts/${m.contact.id}`}>
              <Button size="sm">
                <UserRound className="h-3.5 w-3.5" /> Open contact
              </Button>
            </Link>
          )}
          <Link href={`/calls/${m.call_id}`}>
            <Button size="sm">
              <PhoneCall className="h-3.5 w-3.5" /> View call
            </Button>
          </Link>
        </div>
      </div>
    </Card>
  );
}
