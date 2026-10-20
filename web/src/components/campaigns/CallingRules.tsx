"use client";

import { ArrowRight, ArrowUp, ArrowDown, Clock, Flame, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, Field, Input, Select, Toggle } from "@/components/ui";
import { fetcher, patch } from "@/lib/api";
import type { Campaign, MyPhoneNumbers } from "@/lib/types";

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

const DAY = 1440;

const DELAYS: [number, string][] = [
  [5, "5 minutes"],
  [10, "10 minutes"],
  [15, "15 minutes"],
  [20, "20 minutes"],
  [30, "30 minutes"],
  [45, "45 minutes"],
  [60, "1 hour"],
  [120, "2 hours"],
  [180, "3 hours"],
  [240, "4 hours"],
  [360, "6 hours"],
  [DAY, "1 day"],
  [2 * DAY, "2 days"],
  [3 * DAY, "3 days"],
  [4 * DAY, "4 days"],
  [7 * DAY, "1 week"],
  [14 * DAY, "2 weeks"],
];

const MAX_RETRIES = 10;

const PRESETS: [string, number[], string][] = [
  ["Call once", [], "One call per contact — no follow-ups."],
  ["Double-dial", [5], "Call now, then once more 5 minutes later if they don't answer."],
  ["Daily for 3 days", [DAY, DAY, DAY], "Call now, then again around the same time for the next 3 days."],
  ["5-day follow-up", [15, 20, DAY, 2 * DAY, 2 * DAY], "Most persistent: up to 6 attempts spread over about a week."],
];

export function formatWait(minutes: number): string {
  const hit = DELAYS.find(([m]) => m === minutes);
  if (hit) return hit[1];
  if (minutes % DAY === 0) return `${minutes / DAY} days`;
  if (minutes % 60 === 0) return `${minutes / 60} hours`;
  return `${minutes} minutes`;
}

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
  retry_schedule: number[];
  number_rotation_enabled: boolean;
  caller_number_pool: string[];
  retry_caller_policy: "same" | "different";
  warmup_enabled: boolean;
  warmup_min_gap_seconds: number;
  warmup_max_gap_seconds: number;
  warmup_batch_size: number;
  warmup_rest_seconds: number;
};

function formFrom(c: Campaign): Form {
  return {
    call_window_start: c.call_window_start,
    call_window_end: c.call_window_end,
    call_days: c.call_days,
    timezone: c.timezone,
    number_rotation_enabled: !!c.number_rotation_enabled,
    caller_number_pool: c.caller_number_pool ?? [],
    retry_caller_policy: c.retry_caller_policy ?? "same",
    warmup_enabled: !!c.warmup_enabled,
    warmup_min_gap_seconds: c.warmup_min_gap_seconds ?? 180,
    warmup_max_gap_seconds: c.warmup_max_gap_seconds ?? 300,
    warmup_batch_size: c.warmup_batch_size ?? 10,
    warmup_rest_seconds: c.warmup_rest_seconds ?? 900,
    retry_schedule: c.retry_schedule ?? Array(Math.max(0, c.max_attempts - 1)).fill(c.retry_delay_minutes),
  };
}

export function CallingRulesCard({ campaign, onSaved, onDirtyChange }: { campaign: Campaign; onSaved: () => void; onDirtyChange?: (dirty: boolean) => void }) {
  const toast = useToast();
  const [form, setForm] = useState<Form>(() => formFrom(campaign));
  const [busy, setBusy] = useState(false);
  const { data: phoneNumbers, error: numbersError } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher);
  const activeNumbers = (phoneNumbers?.numbers ?? []).filter((number) => number.status === "active");
  const invalidRotation = form.number_rotation_enabled && (form.caller_number_pool.length < 2 || !!phoneNumbers && form.caller_number_pool.some((number) => !activeNumbers.some((n) => n.number === number)));
  const saved = formFrom(campaign);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  useEffect(() => { onDirtyChange?.(dirty || busy); }, [dirty, busy, onDirtyChange]);

  // Pick up changes made elsewhere while the form is untouched.
  const savedKey = JSON.stringify(saved);
  useEffect(() => {
    if (!busy) setForm(JSON.parse(savedKey));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedKey]);

  const invalidWindow = !form.call_window_start || !form.call_window_end || form.call_window_start >= form.call_window_end;
  const noDays = form.call_days.length === 0;
  const activePreset = PRESETS.find(([, waits]) => JSON.stringify(waits) === JSON.stringify(form.retry_schedule));

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
              <Button size="sm" variant="primary" onClick={save} loading={busy} disabled={invalidWindow || noDays || invalidRotation}>
                Save
              </Button>
            </div>
          ) : undefined
        }
      />
      {dirty && <p className="px-5 pt-3 text-sm font-medium text-amber-700">Save these calling rules before starting or resuming calls. Until saved, the server keeps using the previous schedule.</p>}
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
          <Field label="Time zone" hint="The server uses this saved time zone—not your browser or device. For example, 9 AM Pacific means 9 AM in Los Angeles, including daylight saving changes. Recipient quiet hours can delay a call further.">
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
          <div className="rounded-xl border border-zinc-200 p-4">
            <Toggle checked={form.number_rotation_enabled} onChange={(checked) => setForm((f) => ({ ...f, number_rotation_enabled: checked }))}
              label="Rotate caller numbers" description="Spread calls across the numbers you pick so contacts don't see the same caller ID every time. Off: every call comes from the agent's number or your account default." />
            {form.number_rotation_enabled && <div className="mt-4 space-y-3">
              <p className="text-xs text-zinc-500">Choose at least two active numbers. Use the arrows to set their order. Rotation does not guarantee removal of spam labels.</p>
              {numbersError && <p className="text-xs text-red-600">Could not load your numbers. Try refreshing before saving.</p>}
              {!phoneNumbers && !numbersError && <p className="text-xs text-zinc-500">Loading your numbers…</p>}
              {[...form.caller_number_pool, ...activeNumbers.map((n) => n.number).filter((number) => !form.caller_number_pool.includes(number))].map((number) => {
                const index = form.caller_number_pool.indexOf(number);
                const owned = activeNumbers.find((n) => n.number === number);
                const move = (delta: number) => setForm((f) => { const pool = [...f.caller_number_pool]; [pool[index], pool[index + delta]] = [pool[index + delta], pool[index]]; return { ...f, caller_number_pool: pool }; });
                return <div key={number} className="flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2">
                  <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                    <input type="checkbox" className="accent-brand-600" checked={index >= 0} disabled={index < 0 && form.caller_number_pool.length >= 20}
                      onChange={(e) => setForm((f) => ({ ...f, caller_number_pool: e.target.checked ? [...f.caller_number_pool, number] : f.caller_number_pool.filter((n) => n !== number) }))} />
                    {index >= 0 && <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-brand-100 text-[11px] font-bold text-brand-700">{String.fromCharCode(65 + index)}</span>}
                    <span className="min-w-0 truncate">{number}{owned?.label ? ` · ${owned.label}` : ""}{phoneNumbers && !owned ? " · inactive" : ""}</span>
                  </label>
                  {index >= 0 && <><button type="button" aria-label={`Move ${number} up`} disabled={index === 0} onClick={() => move(-1)} className="rounded p-2 text-zinc-500 disabled:opacity-30"><ArrowUp className="h-3.5 w-3.5" /></button><button type="button" aria-label={`Move ${number} down`} disabled={index === form.caller_number_pool.length - 1} onClick={() => move(1)} className="rounded p-2 text-zinc-500 disabled:opacity-30"><ArrowDown className="h-3.5 w-3.5" /></button></>}
                </div>;
              })}
              {invalidRotation && <p className="text-xs text-red-600">Select at least two active numbers owned by this account.</p>}
              {form.caller_number_pool.length >= 2 && (
                <div className="rounded-lg bg-zinc-50 px-3 py-2.5">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">How calls rotate</div>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-600">
                    {form.caller_number_pool.map((number, i) => (
                      <span key={number} className="flex items-center gap-1.5">
                        {i > 0 && <ArrowRight className="h-3 w-3 text-zinc-400" />}
                        <span className="rounded-full bg-white px-2 py-1 font-semibold text-zinc-700 ring-1 ring-zinc-200">
                          {String.fromCharCode(65 + i)}
                          <span className="ml-1 font-normal text-zinc-500">{number.slice(-4)}</span>
                        </span>
                      </span>
                    ))}
                    <ArrowRight className="h-3 w-3 text-zinc-400" />
                    <span className="text-zinc-500">back to A, and repeat</span>
                  </div>
                </div>
              )}
              <Field label="If we call them again (a retry), use" hint="">
                <Select value={form.retry_caller_policy} onChange={(e) => setForm((f) => ({ ...f, retry_caller_policy: e.target.value as "same" | "different" }))}>
                  <option value="same">The same number as before</option>
                  <option value="different">A different number from the pool</option>
                </Select>
              </Field>
              <p className="-mt-2 text-xs text-zinc-500">
                {form.retry_caller_policy === "same"
                  ? "Same number: the contact sees the caller ID they already saw — it feels familiar, like the same person trying again."
                  : "Different number: we switch to the next number in the pool, so the retry looks like a fresh call from a new line."}
              </p>
            </div>}
          </div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            <RotateCcw className="h-3.5 w-3.5" /> Automatic retries
          </div>
          <p className="-mt-2 text-xs text-zinc-500">
            If someone doesn&apos;t pick up, we redial them on the schedule below — within your calling hours. Anyone who answers is never called again.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map(([label, waits]) => {
              const on = JSON.stringify(waits) === JSON.stringify(form.retry_schedule);
              return (
                <button
                  key={label}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setForm((f) => ({ ...f, retry_schedule: waits }))}
                  className={`h-7 rounded-full border px-3 text-xs font-medium transition-colors ${
                    on ? "border-brand-600 bg-brand-50 text-brand-700" : "border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
          {activePreset && <p className="-mt-2 text-xs text-brand-700">{activePreset[2]}</p>}
          <ol className="space-y-2 text-sm">
            <li className="flex h-9 items-center gap-3">
              <span className="w-16 shrink-0 text-xs font-medium text-zinc-500">1st call</span>
              <span className="text-zinc-700">When the campaign reaches them, within calling hours</span>
            </li>
            {form.retry_schedule.map((wait, i) => (
              <li key={i} className="flex items-center gap-3">
                <span className="w-16 shrink-0 text-xs font-medium text-zinc-500">Retry {i + 1}</span>
                <Select
                  aria-label={`Wait before retry ${i + 1}`}
                  value={wait}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, retry_schedule: f.retry_schedule.map((w, j) => (j === i ? Number(e.target.value) : w)) }))
                  }
                  className="flex-1"
                >
                  {!DELAYS.some(([m]) => m === wait) && <option value={wait}>{formatWait(wait)} later</option>}
                  {DELAYS.map(([m, label]) => (
                    <option key={m} value={m}>
                      {label} later
                    </option>
                  ))}
                </Select>
                <button
                  type="button"
                  aria-label={`Remove retry ${i + 1}`}
                  onClick={() => setForm((f) => ({ ...f, retry_schedule: f.retry_schedule.filter((_, j) => j !== i) }))}
                  className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                >
                  <X className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ol>
          {form.retry_schedule.length < MAX_RETRIES && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                setForm((f) => ({ ...f, retry_schedule: [...f.retry_schedule, f.retry_schedule.length ? f.retry_schedule[f.retry_schedule.length - 1] : 60] }))
              }
            >
              <Plus className="h-4 w-4" /> Add a retry
            </Button>
          )}
          <p className="text-xs text-zinc-500">
            {form.retry_schedule.length === 0
              ? "Each contact is called once."
              : `Up to ${form.retry_schedule.length + 1} calls per contact. Each wait counts from the previous call; a retry that lands outside calling hours waits for the next window.`}
          </p>
          {campaign.pending_retries > 0 && (
            <p className="text-xs text-zinc-500">
              {campaign.pending_retries} contact{campaign.pending_retries === 1 ? " is" : "s are"} waiting for another try.
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          <Flame className="h-3.5 w-3.5" /> Warm-up number
        </div>
        <div className="rounded-xl border border-zinc-200 p-4">
          <Toggle checked={form.warmup_enabled}
            onChange={(checked) => setForm((f) => ({ ...f, warmup_enabled: checked }))}
            label="Warm up this number"
            description="Dial slowly with pauses so a fresh number doesn't register as spam. Pairs with number rotation." />
          {form.warmup_enabled && <div className="mt-4 space-y-3">
            <p className="text-xs text-zinc-500">
              One call at a time, a random gap between calls, and a longer rest after a batch.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Gap between calls">
                <div className="flex items-center gap-2">
                  <Input type="number" min={30} max={3600} value={form.warmup_min_gap_seconds}
                    onChange={(e) => setForm((f) => ({ ...f, warmup_min_gap_seconds: Number(e.target.value) }))}
                    className="w-20" aria-label="Minimum gap seconds" />
                  <span className="text-xs text-zinc-500">to</span>
                  <Input type="number" min={30} max={3600} value={form.warmup_max_gap_seconds}
                    onChange={(e) => setForm((f) => ({ ...f, warmup_max_gap_seconds: Number(e.target.value) }))}
                    className="w-20" aria-label="Maximum gap seconds" />
                  <span className="text-xs text-zinc-500">sec</span>
                </div>
              </Field>
              <Field label="Rest after a batch">
                <div className="flex items-center gap-2">
                  <Input type="number" min={1} max={100} value={form.warmup_batch_size}
                    onChange={(e) => setForm((f) => ({ ...f, warmup_batch_size: Number(e.target.value) }))}
                    className="w-20" aria-label="Calls per batch" />
                  <span className="text-xs text-zinc-500">calls, then</span>
                  <Input type="number" min={60} max={7200} value={form.warmup_rest_seconds}
                    onChange={(e) => setForm((f) => ({ ...f, warmup_rest_seconds: Number(e.target.value) }))}
                    className="w-20" aria-label="Rest seconds" />
                  <span className="text-xs text-zinc-500">sec rest</span>
                </div>
              </Field>
            </div>
            {form.warmup_min_gap_seconds > form.warmup_max_gap_seconds && (
              <p className="text-xs text-red-600">The minimum gap can't be larger than the maximum.</p>
            )}
            <p className="text-xs text-zinc-500">
              At the default settings: roughly 12-20 calls/hour with a 15-minute rest every 10 calls.
              Loosen the gap as the number builds history.
            </p>
          </div>}
        </div>
      </div>
    </Card>
  );
}
