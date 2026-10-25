"use client";
import { CalendarClock, ChevronDown, RotateCcw } from "lucide-react";
import { useEffect } from "react";
import useSWR from "swr";
import { Badge, Button, Card, Notice, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Campaign } from "@/lib/types";

export type Forecast = {
  generated_at: string; timezone: string; campaign_status: string; automatic: boolean;
  next_at: string | null; next_count: number; ready_now: number; new_contacts: number; redials: number;
  active_calls: number; concurrency: number; waiting_for_outcome: number; no_matching_window: number;
  reason: string | null; max_attempts: number; contact_count?: number; window_count?: number;
  retry_plan: { retry: number; delay_minutes: number }[];
  windows: { start_at: string; end_at: string; contacts: number; first_calls: number; redials: number }[];
  contacts: { id: string; name: string; kind: string; attempt: number; retry: number; due_at: string | null; eligible_at: string }[];
};
const waitLabel = (minutes: number) => minutes >= 1440 && minutes % 1440 === 0 ? `${minutes / 1440} day${minutes === 1440 ? "" : "s"}` : minutes >= 60 && minutes % 60 === 0 ? `${minutes / 60} hour${minutes === 60 ? "" : "s"}` : `${minutes} minutes`;

export function CampaignForecast({ campaign, rulesDirty = false }: { campaign: Campaign; rulesDirty?: boolean }) {
  const { data, error, mutate } = useSWR<Forecast>(`/api/campaigns/${campaign.id}/forecast`, fetcher, { refreshInterval: campaign.status === "running" ? 15000 : 30000 });
  useEffect(() => { void mutate(); }, [campaign.updated_at, campaign.status, mutate]);
  const format = (iso: string) => {
    try { return new Intl.DateTimeFormat("en-US", { timeZone: data?.timezone || campaign.timezone, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }).format(new Date(iso)); }
    catch { return "Time unavailable"; }
  };
  const clock = (iso: string) => { try { return new Intl.DateTimeFormat("en-US", { timeZone: data?.timezone || campaign.timezone, hour: "numeric", minute: "2-digit" }).format(new Date(iso)); } catch { return "—"; } };
  const stopped = data?.reason === "cancelled" || data?.reason === "completed";
  return <Card className="mb-6 overflow-hidden">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-100 p-5">
      <div><h2 className="flex items-center gap-2 font-semibold"><CalendarClock className="h-4 w-4 text-brand-600" /> Upcoming calls &amp; redials</h2><p className="mt-1 text-xs text-zinc-500">Based on saved calling hours and retry times.</p></div>
      <div className="flex items-center gap-2"><Badge tone="gray">{data?.timezone || campaign.timezone}</Badge><Button size="sm" variant="ghost" aria-label="Refresh call forecast" onClick={() => void mutate()}><RotateCcw className="h-3.5 w-3.5" /></Button></div>
    </div>
    <div className="space-y-4 p-5">
      {rulesDirty && <Notice tone="amber">This preview uses your saved calling rules. Save your changes to update the forecast.</Notice>}
      {error ? <Notice tone="red">Couldn&apos;t load the call forecast. Use refresh to try again.</Notice> : !data ? <div className="flex justify-center py-6"><Spinner /></div> : <>
        {data.reason === "invalid_timezone" ? <Notice tone="amber">Choose a valid campaign timezone before scheduling calls.</Notice> : data.reason === "agent_required" ? <Notice tone="amber">Select an agent before this campaign can call.</Notice> : data.reason === "account_suspended" ? <Notice tone="amber">Calling is unavailable for this account. The times below are a preview only.</Notice> : stopped ? <p className="text-sm text-zinc-600">This campaign is {data.campaign_status}. No automatic calls are scheduled.</p> : <>
          {!data.automatic && <Notice tone="amber">{data.campaign_status === "paused" ? "Paused — no calls will go out until you resume." : "Draft — no calls will go out until you start."} The times below show earliest eligibility if started or resumed now.</Notice>}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="col-span-2 rounded-xl bg-orange-50 p-3 lg:col-span-1"><div className="text-xs text-zinc-600">Next eligible calls</div><div className="mt-1 text-sm font-semibold text-zinc-900">{data.next_at ? format(data.next_at) : data.no_matching_window ? "No permitted window" : "No calls waiting"}</div><div className="mt-1 text-xs text-zinc-500">{data.next_at ? `${data.next_count} contact${data.next_count === 1 ? "" : "s"} eligible then` : "No next attempt scheduled"}</div></div>
            {[ ["First calls waiting", data.new_contacts], ["Contacts to redial", data.redials], ["Eligible now", data.ready_now] ].map(([label,value]) => <div key={String(label)} className="rounded-xl bg-zinc-50 p-3"><div className="text-xs text-zinc-500">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums">{value}</div></div>)}
          </div>
          {data.windows.length > 0 && <div className="divide-y divide-zinc-100 rounded-xl border border-zinc-200">
            {data.windows.map(w => <div key={w.start_at} className="flex flex-wrap items-center justify-between gap-2 px-3 py-3 text-sm"><div><div className="font-medium">{format(w.start_at)} – {clock(w.end_at)}</div><div className="mt-0.5 text-xs text-zinc-500">{w.first_calls} first calls · {w.redials} redials eligible in this window</div></div><Badge tone="gray">{w.contacts} contacts</Badge></div>)}
          </div>}
          {(data.window_count || 0) > data.windows.length && <p className="text-xs text-zinc-500">Showing the next {data.windows.length} of {data.window_count} eligibility windows.</p>}
          {data.no_matching_window > 0 && <Notice tone="amber">{data.no_matching_window} contacts have no matching campaign/local calling window in the next eight days after they become due. Review your calling hours.</Notice>}
          <p className="text-xs text-zinc-500">{data.active_calls} calls in progress · up to {data.concurrency} concurrent. {data.waiting_for_outcome > 0 ? `${data.waiting_for_outcome} contacts awaiting call outcomes. ` : ""}Eligibility is not a reserved dial time: capacity, credits, warm-up pacing, and caller-number rests can delay calls.</p>
          {data.contacts.length > 0 && <details className="rounded-xl border border-zinc-200 p-3"><summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">Next contacts <ChevronDown className="h-4 w-4" /></summary><div className="mt-3 divide-y divide-zinc-100">{data.contacts.map(c => <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-xs"><div className="min-w-0"><div className="font-medium text-zinc-900 break-words">{c.name}</div><div className="text-zinc-500">{c.kind === "redial" ? `Redial ${c.retry}` : "First call"} · attempt {c.attempt} of {data.max_attempts}</div>{c.due_at && <div className="mt-0.5 text-zinc-400">Retry due {format(c.due_at)}</div>}</div><span className="text-zinc-600">{format(c.eligible_at)}</span></div>)}</div><p className="mt-2 text-xs text-zinc-400">Showing {data.contacts.length} of {data.contact_count} contacts with a next eligible attempt.</p></details>}
        </>}
        {data.retry_plan.length > 0 && <details className="rounded-xl bg-zinc-50 p-3"><summary className="cursor-pointer text-xs font-medium text-zinc-600">How future redials are calculated</summary><div className="mt-2 flex flex-wrap gap-2">{data.retry_plan.map(r => <span key={r.retry} className="rounded-lg border border-zinc-200 bg-white px-2 py-1 text-xs">Redial {r.retry}: {waitLabel(r.delay_minutes)} after attempt {r.retry}</span>)}</div><p className="mt-2 text-xs text-zinc-500">Each later retry depends on an unanswered eligible outcome and remaining attempts. Due times move into allowed calling hours; answered and do-not-call contacts are excluded.</p></details>}
      </>}
    </div>
  </Card>;
}
