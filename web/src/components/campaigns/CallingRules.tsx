"use client";

import { Clock, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, Field, Input, Select } from "@/components/ui";
import { patch } from "@/lib/api";
import type { Campaign } from "@/lib/types";

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export const TIMEZONES: [string, string][] = [
  ["America/New_York", "Eastern (New York)"],
  ["America/Chicago", "Central (Chicago)"],
  ["America/Denver", "Mountain (Denver)"],
  ["America/Phoenix", "Arizona (Phoenix)"],
  ["America/Los_Angeles", "Pacific (Los Angeles)"],
  ["America/Anchorage", "Alaska (Anchorage)"],
  ["Pacific/Honolulu", "Hawaii (Honolulu)"],
  ["America/Toronto", "Toronto"],
  ["Europe/London", "London"],
  ["Europe/Paris", "Paris / Berlin / Madrid"],
  ["Europe/Amsterdam", "Amsterdam"],
  ["UTC", "UTC"],
];

const DELAYS: [number, string][] = [
  [15, "15 minutes"],
  [30, "30 minutes"],
  [60, "1 hour"],
  [120, "2 hours"],
  [240, "4 hours"],
  [1440, "Next day"],
];

/** "09:00" → "9:00 AM" */
export function formatClock(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const suffix = h < 12 ? "AM" : "PM";
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${suffix}`;
}

/** Short zone name like "EDT" or "GMT+1" for a given IANA zone. */
export function tzShort(tz: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }).formatToParts(at).find((p) => p.type === "timeZoneName");
    return part?.value ?? tz;
  } catch {
    return tz;
  }
}

/** [0,1,2,3,4] → "Mon–Fri", [5,6] → "Sat–Sun", [0,2,4] → "Mon, Wed, Fri". */
export function formatDays(days: number[]): string {
  const d = [...new Set(days)].sort((a, b) => a - b);
  if (d.length === 7) return "Every day";
  if (d.length === 0) return "No days";
  const runs: number[][] = [];
  for (const n of d) {
    const last = runs[runs.length - 1];
    if (last && n === last[last.length - 1] + 1) last.push(n);
    else runs.push([n]);
  }
  return runs.map((r) => (r.length >= 3 ? `${WEEKDAYS[r[0]]}–${WEEKDAYS[r[r.length - 1]]}` : r.map((n) => WEEKDAYS[n]).join(", "))).join(", ");
}

/** "9:00 AM–5:00 PM EDT, Mon–Fri" */
export function describeWindow(c: Pick<Campaign, "call_window_start" | "call_window_end" | "call_days" | "timezone">): string {
  return `${formatClock(c.call_window_start)}–${formatClock(c.call_window_end)} ${tzShort(c.timezone)}, ${formatDays(c.call_days)}`;
}

/** "Tue 9:00 AM" in the campaign's own time zone. */
export function formatResume(iso: string, tz: string): string {
  try {
    return new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", hour: "numeric", minute: "2-digit" }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString();
  }
}

/** One-line status for the campaign header. */
export function CallingStatus({ campaign }: { campaign: Campaign }) {
  const hours = describeWindow(campaign);
  const running = campaign.status === "running";
  if (campaign.within_calling_hours) {
    return (
      <p className="flex items-start gap-1.5 text-sm text-zinc-600">
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${running ? "bg-emerald-500" : "bg-zinc-300"}`} />
        <span>
          {running ? "Calling now" : "Inside calling hours"} · window {hours}
        </span>
      </p>
    );
  }
  const next = campaign.next_window_at ? formatResume(campaign.next_window_at, campaign.timezone) : null;
  return (
    <p className="flex items-start gap-1.5 text-sm text-zinc-600">
      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-amber-400" />
      <span>
        Outside calling hours{next ? ` — ${running ? "resumes" : "next window"} ${next}` : ""} · window {hours}
      </span>
    </p>
  );
}

type Form = {
  call_window_start: string;
  call_window_end: string;
  call_days: number[];
  timezone: string;
  max_attempts: number;
  retry_delay_minutes: number;
};

function formFrom(c: Campaign): Form {
  return {
    call_window_start: c.call_window_start,
    call_window_end: c.call_window_end,
    call_days: c.call_days,
    timezone: c.timezone,
    max_attempts: c.max_attempts,
    retry_delay_minutes: c.retry_delay_minutes,
  };
}

export function CallingRulesCard({ campaign, onSaved }: { campaign: Campaign; onSaved: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState<Form>(() => formFrom(campaign));
  const [busy, setBusy] = useState(false);
  const saved = formFrom(campaign);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);

  // Pick up changes made elsewhere while the form is untouched.
  const savedKey = JSON.stringify(saved);
  useEffect(() => {
    if (!busy) setForm(JSON.parse(savedKey));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedKey]);

  const invalidWindow = !form.call_window_start || !form.call_window_end || form.call_window_start >= form.call_window_end;
  const noDays = form.call_days.length === 0;

  function toggleDay(d: number) {
    setForm((f) => ({ ...f, call_days: f.call_days.includes(d) ? f.call_days.filter((x) => x !== d) : [...f.call_days, d].sort((a, b) => a - b) }));
  }

  async function save() {
    setBusy(true);
    try {
      await patch(`/api/campaigns/${campaign.id}`, form);
      toast("Calling rules saved");
      onSaved();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const zones = TIMEZONES.some(([z]) => z === form.timezone) ? TIMEZONES : [[form.timezone, form.timezone] as [string, string], ...TIMEZONES];

  return (
    <Card className="mb-6">
      <CardHeader
        title="Calling rules"
        description="When this campaign may call, and how often it tries people who don't pick up."
        action={
          dirty ? (
            <div className="flex shrink-0 gap-2">
              <Button size="sm" variant="ghost" onClick={() => setForm(saved)}>
                Reset
              </Button>
              <Button size="sm" variant="primary" onClick={save} loading={busy} disabled={invalidWindow || noDays}>
                Save
              </Button>
            </div>
          ) : undefined
        }
      />
      <div className="grid gap-6 p-5 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            <Clock className="h-3.5 w-3.5" /> Calling hours
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="From">
              <Input type="time" step={900} value={form.call_window_start} onChange={(e) => setForm((f) => ({ ...f, call_window_start: e.target.value }))} />
            </Field>
            <Field label="Until">
              <Input type="time" step={900} value={form.call_window_end} onChange={(e) => setForm((f) => ({ ...f, call_window_end: e.target.value }))} />
            </Field>
          </div>
          {invalidWindow && <p className="-mt-2 text-xs text-red-600">The end time has to be after the start time.</p>}
          <div>
            <span className="mb-1.5 block text-xs font-medium text-zinc-700">Days</span>
            <div className="flex flex-wrap gap-1.5">
              {WEEKDAYS.map((label, d) => {
                const on = form.call_days.includes(d);
                return (
                  <button
                    key={label}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggleDay(d)}
                    className={`h-8 min-w-[44px] rounded-full border px-3 text-xs font-medium transition-colors ${
                      on ? "border-brand-600 bg-brand-600 text-white" : "border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            {noDays && <p className="mt-1 text-xs text-red-600">Pick at least one day.</p>}
          </div>
          <Field label="Time zone" hint="Calling hours follow this time zone. We also never ring anyone before 8 AM or after 9 PM their own time.">
            <Select value={form.timezone} onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}>
              {zones.map(([z, label]) => (
                <option key={z} value={z}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            <RotateCcw className="h-3.5 w-3.5" /> Automatic retries
          </div>
          <Field label="If nobody picks up" hint="Unanswered calls and voicemails are tried again. Contacts who answer are never called twice.">
            <Select value={form.max_attempts} onChange={(e) => setForm((f) => ({ ...f, max_attempts: Number(e.target.value) }))}>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n === 1 ? "Call once (no retries)" : `Try up to ${n} times`}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Wait between tries">
            <Select
              value={form.retry_delay_minutes}
              disabled={form.max_attempts <= 1}
              onChange={(e) => setForm((f) => ({ ...f, retry_delay_minutes: Number(e.target.value) }))}
            >
              {!DELAYS.some(([m]) => m === form.retry_delay_minutes) && <option value={form.retry_delay_minutes}>{form.retry_delay_minutes} minutes</option>}
              {DELAYS.map(([m, label]) => (
                <option key={m} value={m}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          {campaign.pending_retries > 0 && (
            <p className="text-xs text-zinc-500">
              {campaign.pending_retries} contact{campaign.pending_retries === 1 ? " is" : "s are"} waiting for another try.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
