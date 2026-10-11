"use client";

import { FileText, Globe, Info, MessageSquare, PhoneCall, PhoneOutgoing, PlayCircle, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import useSWR from "swr";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button, Card, EmptyState, PageHeader, Select, Spinner } from "@/components/ui";
import { formatDay, timeZoneLabel } from "@/components/dashboard/activity-model";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Agent, Call } from "@/lib/types";
import { formatDateTime, formatDuration, humanize } from "@/lib/utils";

const OUTCOMES = ["meeting_booked", "qualified", "interested", "not_interested", "not_qualified", "callback", "transferred", "voicemail", "no_answer", "completed", "failed"];
const OUTCOME_CHIP: Record<string, string> = { meeting_booked: "Meetings booked", transferred: "Transferred" };
const TYPE_CHIP: Record<string, string> = { outbound: "Phone calls", web: "Browser tests" };
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
      <CallLogs />
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
  const agentId = params.get("agent_id") ?? "";
  const outcome = params.get("outcome") ?? "";
  const type = params.get("call_type") ?? "";
  const [page, setPage] = useState(1);

  function setFilter(key: string, value: string) {
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
  const { data, error } = useSWR<{ items: Call[]; total: number }>(`/api/calls/?${qs}`, fetcher, { refreshInterval: 10000 });
  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;
  const tz = session?.org?.timezone;

  const chips: { key: string; label: string; title?: string }[] = [];
  if (date) chips.push({ key: "date", label: formatDay(date), title: tz ? `Calls started on this day, ${timeZoneLabel(tz)}` : undefined });
  if (agentId) chips.push({ key: "agent_id", label: `Agent ${agents?.find((a) => a.id === agentId)?.name ?? "…"}` });
  if (outcome) chips.push({ key: "outcome", label: OUTCOME_CHIP[outcome] ?? humanize(outcome) });
  if (type) chips.push({ key: "call_type", label: TYPE_CHIP[type] ?? humanize(type) });

  return (
    <>
      <PageHeader title="Call Logs" description="Every call with its transcript, AI summary and extracted data." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select className="sm:w-56" value={agentId} onChange={(e) => setFilter("agent_id", e.target.value)} aria-label="Agent">
          <option value="">All agents</option>
          {agents?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <Select className="sm:w-56" value={outcome} onChange={(e) => setFilter("outcome", e.target.value)} aria-label="Outcome">
          <option value="">All outcomes</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {o.replace(/_/g, " ")}
            </option>
          ))}
        </Select>
        <Select className="sm:w-56" value={type} onChange={(e) => setFilter("call_type", e.target.value)} aria-label="Call type">
          <option value="">Phone + browser</option>
          <option value="outbound">Phone calls</option>
          <option value="web">Browser tests</option>
        </Select>
      </div>
      {chips.length > 0 && (
        <div className="-mt-1 mb-4 flex flex-wrap items-center gap-2" aria-label="Active filters">
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
            <button type="button" onClick={() => router.replace(pathname, { scroll: false })} className="text-xs text-zinc-500 underline hover:text-zinc-800">
              Clear all
            </button>
          )}
        </div>
      )}
      <Card>
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
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="border-b border-zinc-100 bg-zinc-50/60 text-left text-xs text-zinc-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Contact</th>
                  <th className="px-4 py-3 font-medium">Number</th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Outcome</th>
                  <th className="px-4 py-3 text-right font-medium">Credits</th>
                  <th className="px-4 py-3 font-medium">Started</th>
                  <th className="px-4 py-3 font-medium">Ended</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {data.items.map((c) => (
                  <tr key={c.id} className="hover:bg-zinc-50/80">
                    <td className="px-5 py-3">
                      <Link href={`/calls/${c.id}`} className="flex items-center gap-2" title={c.summary ?? undefined}>
                        {c.call_type === "web" ? <Globe className="h-4 w-4 shrink-0 text-zinc-400" /> : <PhoneOutgoing className="h-4 w-4 shrink-0 text-zinc-400" />}
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{c.contact_name ?? (c.call_type === "web" ? "Browser test" : "Unknown")}</span>
                          <span className="block truncate text-xs text-zinc-500">{c.agent_name ?? "—"}{c.campaign_name ? ` · ${c.campaign_name}` : ""}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-zinc-600">{c.call_type === "web" ? "Browser" : c.to_phone ?? "—"}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-zinc-700">{durationWords(c.duration_seconds)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-600">{humanize(c.status)}</td>
                    <td className="px-4 py-3">
                      <OutcomeBadge outcome={c.outcome} status={c.status} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      <CreditsCell call={c} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">{formatDateTime(c.started_at)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-500">{c.ended_at ? formatDateTime(c.ended_at) : "—"}</td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-1">
                        <IconLink href={`/calls/${c.id}`} label="Open call details" icon={FileText} />
                        <IconLink href={`/calls/${c.id}#transcript`} label="Transcript" icon={MessageSquare} />
                        {c.has_recording && <IconLink href={`/calls/${c.id}#recording`} label="Play recording" icon={PlayCircle} />}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {data && data.total > PAGE && (
        <div className="mt-4 flex items-center justify-end gap-2 text-xs text-zinc-500">
          Page {page} of {pages}
          <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </>
  );
}

function durationWords(sec: number | null | undefined): string {
  if (!sec) return "—";
  if (sec < 60) return `${sec} second${sec === 1 ? "" : "s"}`;
  return formatDuration(sec);
}

function IconLink({ href, label, icon: Icon }: { href: string; label: string; icon: typeof FileText }) {
  return (
    <Link href={href} title={label} aria-label={label} className="flex h-8 w-8 items-center justify-center rounded-lg text-brand-600 transition hover:bg-brand-50">
      <Icon className="h-4 w-4" />
    </Link>
  );
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
