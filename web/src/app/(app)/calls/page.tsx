"use client";

import { CalendarCheck, CalendarDays, ChevronRight, Clock, Globe, Info, MessageSquare, PhoneCall, PhoneIncoming, PhoneOutgoing, Timer, UserCheck, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useState } from "react";
import useSWR from "swr";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { ContactAvatar, StatusPill } from "@/components/contacts/shared";
import { BentoCard } from "@/components/analytics/Bento";
import type { Analytics } from "@/components/analytics/types";
import { CallAudioProvider, PlayButton } from "@/components/calls/CallAudio";
import { RecordingPlayer } from "@/components/calls/RecordingPlayer";
import { TranscriptLines } from "@/components/calls/Transcript";
import { Button, Card, EmptyState, Field, Input, Modal, PageHeader, Select, Spinner } from "@/components/ui";
import { formatDay, timeZoneLabel } from "@/components/dashboard/activity-model";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Agent, Call } from "@/lib/types";
import { cn, formatDateTime, formatDuration, formatPhone, humanize, outcomeLabel, timeAgo } from "@/lib/utils";

const OUTCOMES = ["meeting_booked", "qualified", "interested", "not_interested", "not_qualified", "callback", "transferred", "voicemail", "screened", "no_answer", "language_barrier", "hung_up", "completed", "failed"];
const OUTCOME_CHIP: Record<string, string> = { meeting_booked: "Meetings booked", transferred: "Transferred" };
const TYPE_CHIP: Record<string, string> = { outbound: "Outbound calls", inbound: "Inbound calls", web: "Browser tests" };
const PAGE = 25;

export default function CallsPage() {
  // useSearchParams needs a Suspense boundary in the App Router.
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      }
    >
      <CallAudioProvider>
        <CallLogs />
      </CallAudioProvider>
    </Suspense>
  );
}

function CallLogs() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { session } = useSession();
  // Filters live in the URL, so a dashboard day link (or a shared link) opens pre-filtered.
  const rawDate = params.get("date") ?? "";
  const date = /^\d{4}-\d{2}-\d{2}$/.test(rawDate) ? rawDate : "";
  const startedFrom = params.get("started_from") ?? "";
  const startedBefore = params.get("started_before") ?? "";
  const agentId = params.get("agent_id") ?? "";
  const outcome = params.get("outcome") ?? "";
  const type = params.get("call_type") ?? "";
  const sort = params.get("sort") ?? "";
  const [page, setPage] = useState(1);
  const [peek, setPeek] = useState<Call | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [draftFrom, setDraftFrom] = useState("");
  const [draftBefore, setDraftBefore] = useState("");
  const [rangeError, setRangeError] = useState("");

  function setRange(from: string, before: string) {
    const next = new URLSearchParams(params.toString());
    next.delete("date");
    next.delete("started_from");
    next.delete("started_before");
    if (from) next.set("started_from", from);
    if (before) next.set("started_before", before);
    setPage(1);
    router.replace(next.size ? `${pathname}?${next}` : pathname, { scroll: false });
    setCalendarOpen(false);
  }

  function setFilter(key: string, value: string) {
    if (key === "range") { setRange("", ""); return; }
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    setPage(1);
    const q = next.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  }

  const qs = new URLSearchParams({ page: String(page), page_size: String(PAGE) });
  if (agentId) qs.set("agent_id", agentId);
  if (outcome) qs.set("outcome", outcome);
  if (type) qs.set("call_type", type);
  if (date) qs.set("date", date);
  if (sort) qs.set("sort", sort);
  if (startedFrom) qs.set("started_from", startedFrom);
  if (startedBefore) qs.set("started_before", startedBefore);
  const { data, error } = useSWR<{ items: Call[]; total: number }>(`/api/calls/?${qs}`, fetcher, { refreshInterval: 10000 });
  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;
  const tz = session?.org?.timezone;

  const rangeText = (value: string) => `${formatDay(value.slice(0, 10))} ${value.slice(11, 16)}`;
  const chips: { key: string; label: string; title?: string }[] = [];
  if (startedFrom || startedBefore) chips.push({ key: "range", label: `${startedFrom ? rangeText(startedFrom) : "Any time"} → ${startedBefore ? rangeText(startedBefore) : "No end"}`, title: tz ? `Call start times, ${timeZoneLabel(tz)}; end time excluded` : "Call start times; end time excluded" });
  if (date) chips.push({ key: "date", label: formatDay(date), title: tz ? `Calls started on this day, ${timeZoneLabel(tz)}` : undefined });
  if (agentId) chips.push({ key: "agent_id", label: `Agent ${agents?.find((a) => a.id === agentId)?.name ?? "…"}` });
  if (outcome) chips.push({ key: "outcome", label: OUTCOME_CHIP[outcome] ?? outcomeLabel(outcome) });
  if (type) chips.push({ key: "call_type", label: TYPE_CHIP[type] ?? humanize(type) });

  return (
    <>
      <PageHeader title="Call Logs" description="Every call with its transcript, AI summary and extracted data." />
      <WeekStats />
      <Modal open={calendarOpen} onClose={() => setCalendarOpen(false)} title="Filter calls by date and time">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (draftFrom && draftBefore && draftBefore <= draftFrom) { setRangeError("Choose an end after the start."); return; } setRange(draftFrom, draftBefore); }}>
          <p className="text-xs text-zinc-500">Call start times in {tz ? timeZoneLabel(tz) : "your account time zone"}. Leave either end blank for an open range. The end time is excluded.</p>
          <Field label="From"><Input aria-label="From date and time" type="datetime-local" value={draftFrom} onChange={(e) => { setDraftFrom(e.target.value); setRangeError(""); }} /></Field>
          <Field label="Until"><Input aria-label="Until date and time" type="datetime-local" value={draftBefore} onChange={(e) => { setDraftBefore(e.target.value); setRangeError(""); }} /></Field>
          {rangeError && <p role="alert" className="text-sm text-red-600">{rangeError}</p>}
          <div className="flex justify-between gap-3">
            <Button type="button" variant="ghost" onClick={() => setRange("", "")}>Clear dates</Button>
            <Button type="submit" variant="primary">Apply</Button>
          </div>
        </form>
      </Modal>
      <Card className="min-w-0 overflow-hidden rounded-2xl">
        <div className="border-b border-zinc-100 px-4 py-4 sm:px-5">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
            <div className="flex min-w-0 items-center gap-2.5 xl:flex-1">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-zinc-700"><PhoneCall className="h-4 w-4" /></span>
              <h2 className="font-semibold text-zinc-900">All calls</h2>
              {data && <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium tabular-nums text-zinc-500">{data.total.toLocaleString()}</span>}
            </div>
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-row sm:flex-wrap sm:items-center">
        <Select className="rounded-full! border-zinc-200 bg-zinc-50 sm:w-44" value={agentId} onChange={(e) => setFilter("agent_id", e.target.value)} aria-label="Agent">
          <option value="">All agents</option>
          {agents?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <Select className="rounded-full! border-zinc-200 bg-zinc-50 sm:w-44" value={outcome} onChange={(e) => setFilter("outcome", e.target.value)} aria-label="Outcome">
          <option value="">All outcomes</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {outcomeLabel(o)}
            </option>
          ))}
        </Select>
        <Select className="rounded-full! border-zinc-200 bg-zinc-50 sm:w-44" value={type} onChange={(e) => setFilter("call_type", e.target.value)} aria-label="Call type">
          <option value="">Phone + browser</option>
          <option value="outbound">Outbound calls</option>
          <option value="inbound">Inbound calls</option>
          <option value="web">Browser tests</option>
        </Select>
        <Select className="rounded-full! border-zinc-200 bg-zinc-50 sm:w-44" value={sort} onChange={(e) => setFilter("sort", e.target.value)} aria-label="Sort">
          <option value="">Newest first</option>
          <option value="longest">Longest calls first</option>
          <option value="shortest">Shortest calls first</option>
        </Select>
        <button type="button" aria-label="Filter calls by date and time" aria-haspopup="dialog" aria-expanded={calendarOpen}
              onClick={() => {
            const endOfDay = date ? new Date(`${date}T00:00:00Z`) : null;
            if (endOfDay && !Number.isNaN(endOfDay.getTime())) endOfDay.setUTCDate(endOfDay.getUTCDate() + 1);
            setDraftFrom(startedFrom || (date ? `${date}T00:00` : ""));
            setDraftBefore(startedBefore || (endOfDay && !Number.isNaN(endOfDay.getTime()) ? `${endOfDay.toISOString().slice(0, 10)}T00:00` : ""));
            setRangeError(""); setCalendarOpen(true);
          }}
              className={cn("col-span-2 inline-flex h-10 items-center justify-center gap-1.5 rounded-full border px-4 text-sm transition hover:bg-zinc-100", date || startedFrom || startedBefore ? "border-brand-300 bg-brand-50 text-brand-700" : "border-zinc-200 bg-zinc-50 text-zinc-600")}>
              <CalendarDays className="h-4 w-4" /> Dates
            </button>
          </div>
          </div>
      {chips.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Active filters">
            {chips.map((c, i) => (
              <span key={c.key} className="contents">
                {i > 0 && <span className="text-xs text-zinc-300" aria-hidden="true">·</span>}
                <span
                  title={c.title}
                  className="inline-flex max-w-full items-center gap-1 rounded-full border border-brand-200 bg-brand-50 py-0.5 pr-1 pl-2.5 text-xs font-medium text-brand-700"
                >
                  <span className="truncate">{c.label}</span>
                  <button
                    type="button"
                    onClick={() => setFilter(c.key, "")}
                    aria-label={`Remove filter: ${c.label}`}
                    className="rounded-full p-0.5 hover:bg-brand-100 focus-visible:outline-2 focus-visible:outline-brand-500"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              </span>
            ))}
            {chips.length > 1 && (
              <button type="button" onClick={() => { setPage(1); router.replace(pathname, { scroll: false }); }} className="text-xs text-zinc-500 underline hover:text-zinc-800">
                Clear all
              </button>
            )}
          </div>
        )}
        </div>
        {error ? (
          <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="Couldn't load calls" description={error.message} />
        ) : !data ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : data.items.length === 0 ? (
          chips.length ? (
            <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="No calls match these filters" description="Remove a filter above to see more calls." />
          ) : (
            <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="No calls found" description="Test an agent or start a campaign — calls show up here." />
          )
        ) : (
          <>
          {/* Phones: one card per call */}
          <ul className="divide-y divide-zinc-100 md:hidden">
            {data.items.map((c) => (
              <li key={c.id}>
                <Link href={`/calls/${c.id}`} className="flex gap-3 px-4 py-3.5 active:bg-zinc-50">
                  <CallAvatar call={c} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-start justify-between gap-2">
                      <span className="truncate font-semibold text-zinc-900">{callName(c)}</span>
                      <span className="shrink-0 pt-0.5 text-[11px] text-zinc-400">{timeAgo(c.started_at)}</span>
                    </span>
                    <span className="block truncate text-xs text-zinc-500">{c.agent_name ?? "—"}{c.campaign_name ? ` · ${c.campaign_name}` : ""}</span>
                    <span className="mt-1.5 flex items-center gap-2">
                      <CallOutcome call={c} />
                      <Length sec={c.duration_seconds} />
                    </span>
                    {c.summary && <span className="mt-1.5 line-clamp-2 block text-xs leading-relaxed text-zinc-600">{c.summary}</span>}
                  </span>
                  {c.has_recording && <span className="self-center" onClick={(e) => e.preventDefault()}><PlayButton id={c.id} label={callName(c)} /></span>}
                </Link>
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[980px] text-sm">
              <thead className="text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                <tr className="border-b border-zinc-100">
                  <th className="px-5 py-3">Call</th>
                  <th className="px-3 py-3">Number</th>
                  <th className="px-3 py-3">Outcome</th>
                  <th className="px-3 py-3">Length</th>
                  <th className="px-3 py-3 text-right">Credits</th>
                  <th className="px-3 py-3">When</th>
                  <th className="px-5 py-3 text-right"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100/80">
                {data.items.map((c, i) => {
                  const day = dayLabel(c.started_at, tz);
                  const showDay = !sort && (i === 0 || dayLabel(data.items[i - 1].started_at, tz) !== day);
                  return (
                  <Fragment key={c.id}>
                  {showDay && (
                    <tr className="bg-zinc-50/70">
                      <td colSpan={7} className="px-5 py-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{day}</td>
                    </tr>
                  )}
                  <tr onClick={() => router.push(`/calls/${c.id}`)} className="group cursor-pointer transition-colors hover:bg-orange-50/40">
                    <td className="max-w-[380px] px-5 py-3.5">
                      <div className="flex min-w-0 items-center gap-3" title={c.summary ?? undefined}>
                        <CallAvatar call={c} />
                        <span className="min-w-0">
                          <span className="flex min-w-0 items-baseline gap-2">
                            <span className="truncate font-semibold text-zinc-900">{callName(c)}</span>
                            <span className="truncate text-xs text-zinc-400">{c.agent_name ?? "—"}{c.campaign_name ? ` · ${c.campaign_name}` : ""}</span>
                          </span>
                          {c.summary && <span className="mt-0.5 block truncate text-xs text-zinc-500">{c.summary}</span>}
                        </span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 tabular-nums text-zinc-600">
                      <span className="inline-flex items-center gap-1.5">
                        {c.call_type === "web" ? <Globe className="h-3.5 w-3.5 text-zinc-400" /> : c.call_type === "inbound" ? <PhoneIncoming className="h-3.5 w-3.5 text-zinc-400" /> : <PhoneOutgoing className="h-3.5 w-3.5 text-zinc-400" />}
                        {c.call_type === "web" ? "Browser" : formatPhone(c.to_phone) || "—"}
                      </span>
                    </td>
                    <td className="px-3 py-3"><CallOutcome call={c} /></td>
                    <td className="whitespace-nowrap px-3 py-3"><Length sec={c.duration_seconds} /></td>
                    <td className="whitespace-nowrap px-3 py-3 text-right"><CreditsCell call={c} /></td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-zinc-500" title={formatDateTime(c.started_at)}>{timeAgo(c.started_at)}</td>
                    <td className="px-5 py-3" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button type="button" onClick={() => setPeek(c)} title="Transcript" aria-label="Transcript" className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900">
                          <MessageSquare className="h-4 w-4" />
                        </button>
                        {c.has_recording ? <PlayButton id={c.id} label={callName(c)} /> : <span className="h-8 w-8" aria-hidden="true" />}
                        <ChevronRight className="h-4 w-4 text-zinc-300 transition group-hover:translate-x-0.5 group-hover:text-zinc-500" />
                      </div>
                    </td>
                  </tr>
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </Card>
      {data && data.total > PAGE && (
        <div className="mt-4 flex items-center justify-end gap-2 text-xs text-zinc-500">
          Page {page} of {pages}
          <Button size="sm" className="rounded-full!" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <Button size="sm" className="rounded-full!" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
      <Modal open={!!peek} onClose={() => setPeek(null)} title={peek ? `${peek.contact_name || (peek.call_type === "web" ? "Browser test" : peek.to_phone || "Call")} · transcript` : ""} wide>
        {peek && <TranscriptPeek call={peek} />}
      </Modal>
    </>
  );
}

function TranscriptPeek({ call: c }: { call: Call }) {
  const { data, error } = useSWR<Call>(`/api/calls/${c.id}`, fetcher);
  const transcript = data?.transcript ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
        <OutcomeBadge outcome={c.outcome} status={c.status} />
        <span>{durationWords(c.duration_seconds)}</span>
        <span>{formatDateTime(c.started_at)}</span>
        <Link href={`/calls/${c.id}`} className="ml-auto font-medium text-brand-700 hover:underline">
          Open full call →
        </Link>
      </div>
      {c.has_recording && <RecordingPlayer callId={c.id} live={false} />}
      {data?.summary && <p className="rounded-xl bg-zinc-50 px-3.5 py-2.5 text-sm leading-relaxed text-zinc-700">{data.summary}</p>}
      <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
        {error ? (
          <p className="text-sm text-red-600">Couldn&apos;t load this call.</p>
        ) : !data ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : transcript.length ? (
          <TranscriptLines transcript={transcript} />
        ) : (
          <p className="text-sm text-zinc-500">No transcript was captured for this call.</p>
        )}
      </div>
    </div>
  );
}

function callName(c: Call) {
  return c.contact_name ?? (c.call_type === "web" ? "Browser test" : formatPhone(c.to_phone) || "Unknown");
}

function CallAvatar({ call: c }: { call: Call }) {
  if (c.call_type === "web")
    return <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-zinc-500"><Globe className="h-4 w-4" /></span>;
  return <ContactAvatar name={c.contact_name || c.to_phone || "?"} />;
}

function CallOutcome({ call: c }: { call: Call }) {
  if (!c.outcome) return <OutcomeBadge outcome={null} status={c.status} />;
  return <StatusPill status={c.outcome} label={outcomeLabel(c.outcome)} />;
}

function Length({ sec }: { sec: number | null | undefined }) {
  if (!sec) return <span className="text-xs text-zinc-300">—</span>;
  // A short bar so long conversations stand out at a glance (full at 5 minutes).
  const w = Math.min(100, Math.max(6, (sec / 300) * 100));
  return (
    <span className="inline-flex items-center gap-2 text-xs tabular-nums text-zinc-700">
      <span className="h-1 w-12 overflow-hidden rounded-full bg-zinc-100">
        <span className={cn("block h-full rounded-full", sec >= 60 ? "bg-gradient-to-r from-orange-400 to-amber-300" : "bg-zinc-300")} style={{ width: `${w}%` }} />
      </span>
      {formatDuration(sec)}
    </span>
  );
}

/** "Today", "Yesterday" or the date, in the account's time zone. */
function dayLabel(iso: string | null | undefined, tz?: string | null): string {
  if (!iso) return "Earlier";
  const key = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: tz || undefined });
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(today.getTime() - 86400000);
  if (key(d) === key(today)) return "Today";
  if (key(d) === key(y)) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric", timeZone: tz || undefined });
}

/** This week at a glance: the same lit glass as Analytics, with the daily trend in the hero. */
function WeekStats() {
  const { data } = useSWR<Analytics>("/api/analytics?days=7", fetcher, { refreshInterval: 60000 });
  if (!data) return <div className="mb-5 h-[172px] animate-pulse rounded-[28px] bg-zinc-900/90" />;
  const f = data.funnel;
  const o = data.outcomes;
  const total = Object.values(o).reduce((a, b) => a + b, 0);
  const noPerson = ["voicemail", "no_answer", "failed", "screened", "in_progress"].reduce((a, k) => a + (o[k] ?? 0), 0);
  const reached = Math.max(0, total - noPerson);
  const reach = total ? Math.round((reached / total) * 100) : 0;
  const days = (data.by_day ?? []).slice(-7);
  const tiles = [
    { label: "Reached a person", value: `${reach}%`, sub: `${reached.toLocaleString()} conversations`, icon: UserCheck, bar: reach },
    { label: "Avg call length", value: formatDuration(data.avg_talk_seconds), sub: "Calls that picked up", icon: Clock },
    { label: "Meetings booked", value: f.booked.toLocaleString(), sub: "Last 7 days", icon: CalendarCheck, gold: true },
  ];
  return (
    <div className="relative mb-5 overflow-hidden rounded-[28px] bg-[#0a0a0b] p-2.5 shadow-[0_30px_60px_-36px_rgba(0,0,0,.6)] sm:p-3">
      <div className="pointer-events-none absolute -left-24 top-[10%] h-[260px] w-[420px] rounded-full bg-[#e2541f] opacity-[.3] blur-[100px]" />
      <div className="pointer-events-none absolute right-[-8%] top-[20%] h-[240px] w-[380px] rounded-full bg-[#7c5cff] opacity-[.16] blur-[110px]" />
      <div className="relative grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-[1.5fr_1fr_1fr_1fr]">
        <BentoCard glow="ember" grain className="col-span-2 lg:col-span-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-[13px] font-medium text-white/85"><PhoneCall className="h-4 w-4" /> Calls this week</div>
              <div className="mt-2 text-[44px] font-extralight leading-none tracking-[-.045em] tabular-nums">{f.dialed.toLocaleString()}</div>
              <div className="mt-1.5 text-xs text-white/60">{data.total_minutes.toLocaleString()} min of talk time</div>
            </div>
            <Spark days={days} />
          </div>
        </BentoCard>
        {tiles.map((t, i) => (
          <BentoCard key={t.label} className={cn(i === tiles.length - 1 && "col-span-2 lg:col-span-1")}>
            <div className="flex items-center gap-2 text-[12.5px] font-medium text-white/70">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/10"><t.icon className="h-3.5 w-3.5" /></span>
              <span className="leading-tight">{t.label}</span>
            </div>
            <div className={cn("mt-3 text-[32px] font-extralight leading-none tracking-[-.04em] tabular-nums", t.gold && "text-[#ffd84d]")}>{t.value}</div>
            {t.bar != null ? (
              <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-gradient-to-r from-[#ff8a57] to-[#ffd84d]" style={{ width: `${t.bar}%` }} /></div>
            ) : (
              <div className="mt-1.5 truncate text-xs text-white/40">{t.sub}</div>
            )}
          </BentoCard>
        ))}
      </div>
    </div>
  );
}

/** Seven little bars: calls per day, today on the right. */
function Spark({ days }: { days: { date: string; dialed: number; booked: number }[] }) {
  if (days.length < 2) return null;
  const max = Math.max(1, ...days.map((d) => d.dialed));
  return (
    <div className="flex h-16 items-end gap-1.5 pt-1" aria-hidden="true">
      {days.map((d, i) => (
        <div key={d.date} className="flex flex-col items-center gap-1" title={`${formatDay(d.date)}: ${d.dialed} calls`}>
          <div className={cn("w-2.5 rounded-full", i === days.length - 1 ? "bg-white" : "bg-white/35")} style={{ height: `${Math.max(8, (d.dialed / max) * 52)}px` }} />
          {d.booked > 0 ? <span className="h-1.5 w-1.5 rounded-full bg-[#ffd84d]" /> : <span className="h-1.5 w-1.5" />}
        </div>
      ))}
    </div>
  );
}

function durationWords(sec: number | null | undefined): string {
  if (!sec) return "—";
  if (sec < 60) return `${sec} second${sec === 1 ? "" : "s"}`;
  return formatDuration(sec);
}

/** "1.083" with an ⓘ that explains how it adds up. */
function CreditsCell({ call: c }: { call: Call }) {
  if (c.credits_used == null) return <span className="text-zinc-300">—</span>;
  const b = c.credit_breakdown;
  const lines = b
    ? [
        `AI time: ${b.ai.toFixed(3)} (${b.rate} credit${b.rate === 1 ? "" : "s"}/min, billed per second)`,
        c.call_type === "web" ? (b.free_seconds ? `${b.free_seconds}s covered by free test minutes` : "Browser test — no phone fee") : `Phone line: ${b.phone_fee.toFixed(3)} (per started minute)`,
      ]
    : [];
  const tip = c.credits_used === 0 ? (c.call_type === "web" ? "Free test minutes" : "No charge — the call didn't connect") : lines.join("\n");
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums text-zinc-900" title={tip}>
      {c.credits_used.toFixed(c.credits_used ? 3 : 0)}
      <Info className="h-3.5 w-3.5 text-brand-500" aria-label={tip} />
    </span>
  );
}
