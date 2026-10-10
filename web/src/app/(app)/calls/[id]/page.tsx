"use client";

import { ArrowLeft, Calendar, Clock, ExternalLink, RefreshCw, Sparkles, Wrench } from "lucide-react";
import Link from "next/link";
import { use } from "react";
import useSWR from "swr";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Notice, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { Call } from "@/lib/types";
import { cn, formatDateTime, formatDuration, humanize } from "@/lib/utils";

function fmtTs(ts?: number) {
  if (ts === undefined) return "";
  const s = Math.max(0, Math.round(ts));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function CallDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const toast = useToast();
  const { data: call, error, mutate } = useSWR<Call>(`/api/calls/${id}`, fetcher, {
    refreshInterval: (c) => (!c || !c.ended_at || !c.summary ? 4000 : 0),
  });

  if (error) return <Notice tone="red">{error.message}</Notice>;
  if (!call)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );

  const live = !call.ended_at;
  const extracted = Object.entries(call.extracted_data ?? {}).filter(([k]) => !k.startsWith("_"));
  const successful = (call.extracted_data ?? {})["_successful"];

  return (
    <>
      <Link href="/calls" className="mb-4 inline-flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-3 w-3" /> Call logs
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{call.contact_name ?? call.to_phone ?? "Call"}</h1>
            <OutcomeBadge outcome={call.outcome} status={call.status} />
            {call.sentiment && <Badge tone={call.sentiment === "positive" ? "green" : call.sentiment === "negative" ? "red" : "gray"}>{humanize(call.sentiment)} sentiment</Badge>}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" /> {formatDateTime(call.started_at)}
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" /> {formatDuration(call.duration_seconds)}
            </span>
            <span>{call.call_type === "web" ? "Browser test" : `Phone · ${call.to_phone ?? ""}`}</span>
            {call.agent_id && (
              <Link href={`/agents/${call.agent_id}`} className="text-brand-600 hover:underline">
                {call.agent_name}
              </Link>
            )}
            {call.campaign_id && (
              <Link href={`/campaigns/${call.campaign_id}`} className="text-brand-600 hover:underline">
                {call.campaign_name}
              </Link>
            )}
          </div>
        </div>
        {!live && (
          <Button
            size="sm"
            onClick={async () => {
              await post(`/api/calls/${id}/analyze`).catch((e) => toast(e.message, "error"));
              toast("Re-analyzing — refreshes in a few seconds");
              setTimeout(() => mutate(), 5000);
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" /> Re-analyze
          </Button>
        )}
      </div>

      {live && <div className="mb-6"><Notice tone="blue">This call is still in progress. The transcript and AI summary appear when it ends.</Notice></div>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <CardHeader title="Transcript" />
          <div className="space-y-3 p-5">
            {!call.transcript?.length && <p className="text-sm text-zinc-500">{live ? "Waiting for the call to finish…" : "No transcript was captured."}</p>}
            {call.transcript?.map((t, i) =>
              t.role === "tool" ? (
                <div key={i} className="flex items-center gap-2 pl-1 text-[11px] text-zinc-500">
                  <Wrench className="h-3 w-3" />
                  <span className="font-mono font-medium text-zinc-700">{t.tool}</span>
                  <span className="truncate">{JSON.stringify(t.args ?? {})}</span>
                  <span className="ml-auto shrink-0">{fmtTs(t.ts)}</span>
                </div>
              ) : (
                <div key={i} className={cn("flex gap-3", t.role === "user" && "flex-row-reverse")}>
                  <div
                    className={cn(
                      "max-w-[80%] rounded-2xl px-3.5 py-2 text-sm",
                      t.role === "user" ? "rounded-tr-sm bg-brand-600 text-white" : "rounded-tl-sm bg-zinc-100 text-zinc-800",
                    )}
                  >
                    {t.text}
                  </div>
                  <span className="self-end text-[10px] text-zinc-400">{fmtTs(t.ts)}</span>
                </div>
              ),
            )}
          </div>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title={<span className="flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-brand-600" /> AI summary</span>} />
            <div className="p-5 text-sm leading-relaxed text-zinc-700">
              {call.summary ?? <span className="text-zinc-500">{live ? "Generated after the call." : "Not available — needs OPENAI_API_KEY on the backend and a transcript."}</span>}
              {successful !== undefined && successful !== null && (
                <div className="mt-3">
                  <Badge tone={successful ? "green" : "gray"}>{successful ? "Met success criteria" : "Did not meet success criteria"}</Badge>
                </div>
              )}
            </div>
          </Card>
          <Card>
            <CardHeader title="Extracted data" />
            <dl className="divide-y divide-zinc-100">
              {extracted.length === 0 && <p className="px-5 py-4 text-sm text-zinc-500">Nothing extracted yet.</p>}
              {extracted.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 px-5 py-2.5 text-sm">
                  <dt className="font-mono text-xs text-zinc-500">{k}</dt>
                  <dd className="text-right text-zinc-800">{v === null || v === undefined || v === "" ? "—" : String(v)}</dd>
                </div>
              ))}
            </dl>
          </Card>
          {(call.meeting_link || call.agreed_meeting_time) && (
            <Card className="p-5">
              <div className="text-xs font-medium text-zinc-500">Meeting</div>
              <div className="mt-1 text-sm font-medium">{call.agreed_meeting_time}</div>
              {call.prospect_email && <div className="text-xs text-zinc-500">{call.prospect_email}</div>}
              {call.meeting_link && (
                <a href={call.meeting_link} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600">
                  Open booking <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
