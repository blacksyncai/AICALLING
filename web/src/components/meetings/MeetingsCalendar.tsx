"use client";

import { CalendarClock, ChevronLeft, ChevronRight, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { Slider } from "@/components/ui/slider";
import {
  Timeline,
  TimelineBlock,
  TimelineGrid,
  TimelineHeader,
  TimelineNowLine,
  TimelineProvider,
  TimelineRow,
  TimelineSlot,
  TimelineSlotContent,
  TimelineSlotLabel,
  formatClock,
  minutesToTime,
  timeToMinutes,
  type TimelineRowData,
  type TimelineSlotData,
} from "@/components/ui/timeline";
import { fetcher } from "@/lib/api";
import { cn } from "@/lib/utils";
import { localParts, toIsoWithOffset } from "./MeetingTimeModal";
import type { BusyEvent, Meeting } from "./types";

const DAY = 86400000;

function shiftDays(d: Date, days: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + days, d.getHours(), d.getMinutes());
}

function startOfWeek(d: Date): Date {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); // Monday
  return x;
}

const STATUS_STYLE: Record<string, string> = {
  scheduled: "border-l-brand-500 bg-brand-50",
  completed: "border-l-emerald-500 bg-emerald-50",
  no_show: "border-l-amber-500 bg-amber-50",
  cancelled: "border-l-zinc-300 bg-zinc-50 opacity-60",
};

type Slot = TimelineSlotData & { meeting: Meeting };
type Block = { rowId: string; startTime: string; duration: number; title: string; id: string };

/** Week view of booked meetings: one row per day, drag a meeting to move it. */
export function MeetingsCalendar({
  meetings,
  googleConnected,
  onMove,
  onOpen,
  onSetTime,
}: {
  meetings: Meeting[];
  googleConnected: boolean;
  onMove: (m: Meeting, startIso: string) => Promise<boolean>;
  onOpen: (m: Meeting) => void;
  onSetTime: (m: Meeting) => void;
}) {
  // Open on this week, or on the week of the next upcoming meeting when this week has none left.
  const [week, setWeek] = useState(() => {
    const now = Date.now();
    const next = meetings
      .filter((m) => m.start && m.follow_up_status === "scheduled" && new Date(m.start).getTime() >= now)
      .map((m) => new Date(m.start!).getTime())
      .sort((a, b) => a - b)[0];
    const thisWeek = startOfWeek(new Date());
    return next && next >= thisWeek.getTime() + 7 * DAY ? startOfWeek(new Date(next)) : thisWeek;
  });
  const [zoom, setZoom] = useState(100);
  const weekEnd = shiftDays(week, 7); // calendar days, so a daylight-saving change doesn't shift the week
  const todayId = localParts(new Date()).date;

  const rows: TimelineRowData[] = useMemo(
    () =>
      Array.from({ length: 7 }, (_, i) => {
        const d = new Date(week.getFullYear(), week.getMonth(), week.getDate() + i);
        return { id: localParts(d).date, label: d.toLocaleDateString(undefined, { weekday: "short" }), day: d.getDate(), month: d.toLocaleDateString(undefined, { month: "short" }) };
      }),
    [week],
  );

  const { data: busy } = useSWR<{ connected: boolean; events: BusyEvent[]; error?: string }>(
    googleConnected ? `/api/calendar/events?start=${encodeURIComponent(week.toISOString())}&end=${encodeURIComponent(weekEnd.toISOString())}` : null,
    fetcher,
    { revalidateOnFocus: false },
  );

  const slots: Slot[] = useMemo(
    () =>
      meetings
        .filter((m) => m.start && new Date(m.start) >= week && new Date(m.start) < weekEnd)
        .map((m) => {
          const p = localParts(new Date(m.start!));
          return { id: m.call_id, rowId: p.date, startTime: p.time, duration: m.duration_minutes || 30, meeting: m };
        }),
    [meetings, week, weekEnd],
  );

  const blocks: Block[] = useMemo(
    () =>
      (busy?.events ?? []).flatMap((e) => {
        const s = new Date(e.start);
        const en = e.end ? new Date(e.end) : new Date(s.getTime() + 30 * 60000);
        const p = localParts(s);
        const minutes = Math.max(15, Math.round((en.getTime() - s.getTime()) / 60000));
        return [{ id: e.id, rowId: p.date, startTime: p.time, duration: Math.min(minutes, 24 * 60 - timeToMinutes(p.time)), title: e.title }];
      }),
    [busy],
  );

  // Show 8 AM–7 PM, widened to fit anything booked or busy this week.
  const hours = useMemo(() => {
    let start = 8;
    let end = 19;
    for (const x of [...slots, ...blocks]) {
      const s = timeToMinutes(x.startTime);
      start = Math.min(start, Math.floor(s / 60));
      end = Math.max(end, Math.min(24, Math.ceil((s + x.duration) / 60)));
    }
    return { startHour: start, endHour: end };
  }, [slots, blocks]);

  // Scroll the grid sideways to the week's first meeting (matters on narrow screens).
  const wrap = useRef<HTMLDivElement>(null);
  const firstStart = slots.length ? Math.min(...slots.map((s) => timeToMinutes(s.startTime))) : null;
  useEffect(() => {
    if (firstStart == null) return;
    // After the timeline has measured its width (it does so ~100ms after mount).
    const t = setTimeout(() => {
      const grid = wrap.current?.querySelector<HTMLElement>("[data-slot=timeline-grid]");
      if (!grid) return;
      const ppm = (grid.scrollWidth - 96) / ((hours.endHour - hours.startHour) * 60);
      grid.scrollLeft = Math.max(0, (firstStart - hours.startHour * 60 - 30) * ppm);
    }, 250);
    return () => clearTimeout(t);
  }, [week, firstStart, hours, zoom]);

  const unscheduled = meetings.filter((m) => !m.start && m.follow_up_status === "scheduled");
  const byId = new Map(slots.map((s) => [s.id, s]));

  function overlapsBusy(rowId: string, time: string, duration: number) {
    const a = timeToMinutes(time);
    return blocks.some((b) => b.rowId === rowId && a < timeToMinutes(b.startTime) + b.duration && timeToMinutes(b.startTime) < a + duration);
  }

  const last = shiftDays(weekEnd, -1);
  const weekLabel = `${week.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${
    week.getMonth() === last.getMonth() ? last.getDate() : last.toLocaleDateString(undefined, { month: "short", day: "numeric" })
  }, ${last.getFullYear()}`;
  const navBtn = "flex h-9 w-9 items-center justify-center rounded-full text-zinc-600 transition hover:bg-zinc-100 hover:text-zinc-900";

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-1">
          <button type="button" className={navBtn} onClick={() => setWeek(shiftDays(week, -7))} aria-label="Previous week">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setWeek(startOfWeek(new Date()))}
            className="h-9 rounded-full bg-zinc-100 px-4 text-sm font-medium text-zinc-800 transition hover:bg-zinc-200/80"
          >
            Today
          </button>
          <button type="button" className={navBtn} onClick={() => setWeek(shiftDays(week, 7))} aria-label="Next week">
            <ChevronRight className="h-4 w-4" />
          </button>
          <h3 className="ml-2 font-display text-base font-semibold tracking-tight text-zinc-900">{weekLabel}</h3>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="flex items-center gap-3 text-xs text-zinc-500">
            <Legend className="bg-brand-500" label="Scheduled" />
            <Legend className="bg-emerald-500" label="Completed" />
            {googleConnected && <Legend className="bg-zinc-300" label="Busy (Google)" />}
          </div>
          <label className="flex w-40 items-center gap-2 text-xs text-zinc-500">
            <ZoomIn className="h-3.5 w-3.5 shrink-0" />
            <Slider aria-label="Zoom" min={40} max={100} step={5} value={[zoom]} onValueChange={(v) => setZoom(v[0])} />
          </label>
        </div>
      </div>

      {unscheduled.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-amber-50/70 px-4 py-3 ring-1 ring-inset ring-amber-200/70">
          <span className="mr-1 flex items-center gap-1.5 text-xs font-semibold text-amber-900">
            <CalendarClock className="h-3.5 w-3.5" /> {unscheduled.length} without a confirmed time
          </span>
          {unscheduled.map((m) => (
            <button
              key={m.call_id}
              type="button"
              onClick={() => onSetTime(m)}
              title={m.meeting_time ? `Agreed on the call: "${m.meeting_time}"` : undefined}
              className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-medium text-zinc-800 shadow-sm ring-1 ring-amber-200 transition hover:ring-amber-400"
            >
              <span className="truncate">{m.contact?.name || m.to_phone || "Contact"}</span>
              <span className="shrink-0 text-amber-700">Set time</span>
            </button>
          ))}
        </div>
      )}

      {busy?.error && <p className="text-xs text-amber-700">{busy.error}</p>}

      <div ref={wrap}>
      <TimelineProvider
        config={{ ...hours, snapIntervalMinutes: 15, columnWidth: 96 }}
        percentageInView={zoom}
        onSlotClick={(id) => {
          const s = byId.get(id);
          if (s) onOpen(s.meeting);
        }}
        onValidateDrop={(id, time, rowId) => {
          const s = byId.get(id);
          return !!s && !overlapsBusy(rowId, time, s.duration);
        }}
        onSlotPositionChange={async (id, time, rowId) => {
          const s = byId.get(id);
          return s ? onMove(s.meeting, toIsoWithOffset(rowId, time)) : false;
        }}
      >
        <Timeline slots={slots} rows={rows}>
          <TimelineGrid>
            <TimelineHeader columnLabel="Day" />
            {rows.map((row) => {
              const today = row.id === todayId;
              return (
                <TimelineRow
                  key={row.id}
                  row={row}
                  slots={slots}
                  className={today ? "bg-brand-50/30 [&>[data-slot=timeline-row-label]]:bg-brand-50" : undefined}
                  renderRowHeader={(r) => (
                    <div className="flex items-center gap-2.5 px-4">
                      <span
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-full font-display text-sm font-semibold tabular-nums",
                          today ? "bg-brand-600 text-white" : "text-zinc-900",
                        )}
                      >
                        {r.day}
                      </span>
                      <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">{r.label}</span>
                    </div>
                  )}
                  extra={
                    <>
                      {blocks
                        .filter((b) => b.rowId === row.id)
                        .map((b) => (
                          <TimelineBlock
                            key={b.id}
                            startTime={b.startTime}
                            duration={b.duration}
                            title={`${b.title} · ${formatClock(b.startTime)}`}
                            className="bg-[repeating-linear-gradient(135deg,#f4f4f5_0px,#f4f4f5_6px,#e4e4e7_6px,#e4e4e7_7px)] ring-1 ring-inset ring-zinc-200"
                          >
                            <span className="block truncate px-2 pt-1.5 text-[11px] font-medium text-zinc-500">{b.title}</span>
                          </TimelineBlock>
                        ))}
                      {today && <TimelineNowLine />}
                    </>
                  }
                >
                  {(slot) => {
                    const m = (slot as Slot).meeting;
                    const draggable = m.follow_up_status === "scheduled";
                    return (
                      <TimelineSlot
                        slot={slot}
                        draggable={draggable}
                        className={cn("border-l-4 ring-1 ring-inset ring-zinc-900/5", STATUS_STYLE[m.follow_up_status] ?? STATUS_STYLE.scheduled)}
                      >
                        <div className="px-2 py-1.5">
                          <TimelineSlotLabel className="text-zinc-900">{m.contact?.name || m.to_phone || "Meeting"}</TimelineSlotLabel>
                          <TimelineSlotContent className="truncate text-zinc-500">
                            {formatClock(slot.startTime)}–{formatClock(minutesToTime(timeToMinutes(slot.startTime) + slot.duration))}
                            {m.agent_name ? ` · ${m.agent_name}` : ""}
                          </TimelineSlotContent>
                        </div>
                      </TimelineSlot>
                    );
                  }}
                </TimelineRow>
              );
            })}
          </TimelineGrid>
        </Timeline>
      </TimelineProvider>
      </div>
      <p className="text-xs text-zinc-500">
        Drag a scheduled meeting to move it{googleConnected ? " — it moves on Google Calendar too and can't land on a busy slot" : ""}. Click one for details.
      </p>
    </div>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", className)} />
      {label}
    </span>
  );
}
