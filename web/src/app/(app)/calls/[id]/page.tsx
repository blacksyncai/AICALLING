"use client";

import { ArrowLeft, Calendar, Clock, Coins, ExternalLink, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import useSWR from "swr";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { RecordingPlayer } from "@/components/calls/RecordingPlayer";
import { TranscriptLines } from "@/components/calls/Transcript";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Notice, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { Call } from "@/lib/types";
import { formatCredits, formatDateTime, formatDuration, humanize, parseDate } from "@/lib/utils";


export default function CallDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const toast = useToast();
  const { data: call, error, mutate } = useSWR<Call>(`/api/calls/${id}`, fetcher, {
    // Live calls, plus a short window after the end while the summary is written (some calls never get one).
    refreshInterval: (c) =>
      !c || !c.ended_at || (!c.summary && Date.now() - (parseDate(c.ended_at)?.getTime() ?? 0) < 120_000) ? 4000 : 0,
  });
  const [reanalyzing, setReanalyzing] = useState(false);

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
            {call.credits_used != null && (
              <span className="flex items-center gap-1" title="Billed per second of connected talk time at the agent's rate">
                <Coins className="h-3 w-3" /> {call.credits_used ? `${formatCredits(call.credits_used)} credits` : "No charge (didn't connect)"}
              </span>
            )}
            <span>
              {call.call_type === "web"
                ? "Browser test"
                : call.call_type === "inbound"
                  ? `Inbound call · from ${call.to_phone ?? call.from_phone ?? "unknown number"}`
                  : `Phone · ${call.to_phone ?? ""}${call.from_phone ? ` (from ${call.from_phone})` : ""}`}
            </span>
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
            loading={reanalyzing}
            onClick={async () => {
              setReanalyzing(true);
              try {
                await post(`/api/calls/${id}/analyze`);
                toast("Re-analyzing — refreshes in a few seconds");
                setTimeout(() => {
                  mutate();
                  setReanalyzing(false);
                }, 5000);
              } catch (e) {
                toast(e instanceof Error ? e.message : "Couldn't re-analyze", "error");
                setReanalyzing(false);
              }
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" /> Re-analyze
          </Button>
        )}
      </div>

      {live && <div className="mb-6"><Notice tone="blue">This call is still in progress. The transcript and AI summary appear when it ends.</Notice></div>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card id="transcript" className="scroll-mt-6">
          <CardHeader title="Transcript" />
          <div className="space-y-3 p-5">
            {!call.transcript?.length && <p className="text-sm text-zinc-500">{live ? "Waiting for the call to finish…" : "No transcript was captured."}</p>}
            {call.transcript?.length ? <TranscriptLines transcript={call.transcript} /> : null}
          </div>
        </Card>

        <div className="space-y-6">
          {call.has_recording && (
            <div id="recording" className="scroll-mt-6">
              <RecordingPlayer callId={id} live={live} />
            </div>
          )}
          <Card>
            <CardHeader title={<span className="flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-brand-600" /> AI summary</span>} />
            <div className="p-5 text-sm leading-relaxed text-zinc-700">
              {call.summary ?? <span className="text-zinc-500">{live ? "Generated after the call." : call.transcript?.length ? "No summary for this call." : "No summary — nothing was said on this call."}</span>}
              {successful !== undefined && successful !== null && (
                <div className="mt-3">
                  <Badge tone={successful ? "green" : "gray"}>{successful ? "Met success criteria" : "Did not meet success criteria"}</Badge>
                </div>
              )}
            </div>
          </Card>
          {call.metrics && (
            <Card>
              <CardHeader title="Response time" description={call.metrics.response_metric === "session_state_gap" ? `Observed speech gaps over ${call.metrics.response_gap_samples} turns · excludes carrier playback delay` : `Pipeline estimate over ${call.metrics.turns} agent turns · stages may overlap`} />
              <div className="p-5">
                <div className="text-2xl font-semibold tabular-nums">{call.metrics.avg_response.toFixed(2)}s</div>
                <dl className="mt-3 space-y-1.5 text-xs">
                  {[
                    ...(call.metrics.response_metric === "session_state_gap" ? [
                      ["Typical gap (median)", call.metrics.p50_turn_gap],
                      ["Slow-tail gap (95th percentile)", call.metrics.p95_turn_gap],
                      ["Longest gap", call.metrics.max_turn_gap],
                      ["Interruption recovery", call.metrics.avg_interruption_recovery],
                    ] : []),
                    ["Waiting for caller to finish", call.metrics.avg_eou],
                    ["AI thinking time", call.metrics.avg_llm_ttft],
                    ["Voice start time", call.metrics.avg_tts_ttfb],
                  ].map(([label, v]) => (
                    <div key={label as string} className="flex justify-between gap-3">
                      <dt className="text-zinc-500">{label}</dt>
                      <dd className="tabular-nums text-zinc-800">{v == null ? "—" : `${Number(v).toFixed(2)}s`}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </Card>
          )}
          <Card>
            <CardHeader title="Extracted data" />
            <dl className="divide-y divide-zinc-100">
              {extracted.length === 0 && <p className="px-5 py-4 text-sm text-zinc-500">Nothing extracted yet.</p>}
              {extracted.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 px-5 py-2.5 text-sm">
                  <dt className="text-xs text-zinc-500">{humanize(k)}</dt>
                  <dd className="text-right text-zinc-800">{v === null || v === undefined || v === "" ? "—" : Array.isArray(v) ? v.map(String).join(", ") : typeof v === "object" ? Object.entries(v as Record<string, unknown>).map(([a, b]) => `${humanize(a)}: ${String(b)}`).join(" · ") : String(v)}</dd>
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
