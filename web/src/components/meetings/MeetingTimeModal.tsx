"use client";

import { useEffect, useState } from "react";
import { Button, Field, Input, Modal, Select } from "@/components/ui";
import type { Meeting } from "./types";

const DURATIONS = [15, 30, 45, 60, 90];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

/** Local "YYYY-MM-DD" and "HH:MM" for a date input. */
export function localParts(d: Date): { date: string; time: string } {
  return { date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, time: `${pad(d.getHours())}:${pad(d.getMinutes())}` };
}

/** Local date + time → ISO with the browser's offset (what the API expects). */
export function toIsoWithOffset(date: string, time: string): string {
  const d = new Date(`${date}T${time}:00`);
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  return `${date}T${time}:00${sign}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`;
}

/** Pick or change a meeting's date, time and length. */
export function MeetingTimeModal({
  meeting,
  onClose,
  onSave,
}: {
  meeting: Meeting | null;
  onClose: () => void;
  onSave: (start: string | null, minutes: number) => Promise<void>;
}) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("10:00");
  const [minutes, setMinutes] = useState(30);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!meeting) return;
    const base = meeting.start ? new Date(meeting.start) : new Date(Date.now() + 86400000);
    const p = localParts(base);
    setDate(p.date);
    setTime(meeting.start ? p.time : "10:00");
    setMinutes(meeting.duration_minutes || 30);
  }, [meeting]);

  async function save(start: string | null) {
    setSaving(true);
    try {
      await onSave(start, minutes);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  const who = meeting?.contact?.name || meeting?.to_phone || "this contact";
  return (
    <Modal open={!!meeting} onClose={onClose} title={meeting?.start ? "Change meeting time" : "Set meeting time"}>
      {meeting && (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600">
            Meeting with <span className="font-medium text-zinc-900">{who}</span>
            {meeting.meeting_time && (
              <>
                {" "}— on the call they agreed to <span className="font-medium text-zinc-900">&ldquo;{meeting.meeting_time}&rdquo;</span>.
              </>
            )}
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Date">
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </Field>
            <Field label="Time">
              <Input type="time" step={300} value={time} onChange={(e) => setTime(e.target.value)} />
            </Field>
            <Field label="Length">
              <Select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                {DURATIONS.map((d) => (
                  <option key={d} value={d}>
                    {d < 60 ? `${d} min` : `${d / 60} hr${d > 60 ? "s" : ""}`.replace("1.5 hrs", "1½ hrs")}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <p className="text-xs text-zinc-500">Times are in your time zone ({Intl.DateTimeFormat().resolvedOptions().timeZone}).</p>
          <div className="flex flex-wrap justify-between gap-2">
            {meeting.start_source === "set" ? (
              <Button variant="ghost" onClick={() => void save(null)} disabled={saving}>
                Clear time
              </Button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <Button onClick={onClose}>Cancel</Button>
              <Button variant="primary" loading={saving} disabled={!date || !time} onClick={() => void save(toIsoWithOffset(date, time))}>
                Save time
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
