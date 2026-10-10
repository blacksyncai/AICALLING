"use client";

import { Globe, PhoneCall, PhoneOutgoing } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button, Card, EmptyState, PageHeader, Select, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Agent, Call } from "@/lib/types";
import { formatDateTime, formatDuration } from "@/lib/utils";

const OUTCOMES = ["meeting_booked", "qualified", "interested", "not_interested", "not_qualified", "callback", "transferred", "voicemail", "no_answer", "completed", "failed"];
const PAGE = 25;

export default function CallsPage() {
  const [agentId, setAgentId] = useState("");
  const [outcome, setOutcome] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const qs = new URLSearchParams({ page: String(page), page_size: String(PAGE) });
  if (agentId) qs.set("agent_id", agentId);
  if (outcome) qs.set("outcome", outcome);
  if (type) qs.set("call_type", type);
  const { data, error } = useSWR<{ items: Call[]; total: number }>(`/api/calls/?${qs}`, fetcher, { refreshInterval: 10000 });
  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;

  return (
    <>
      <PageHeader title="Call Logs" description="Every call with its transcript, AI summary and extracted data." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select className="w-auto" value={agentId} onChange={(e) => (setAgentId(e.target.value), setPage(1))}>
          <option value="">All agents</option>
          {agents?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <Select className="w-auto" value={outcome} onChange={(e) => (setOutcome(e.target.value), setPage(1))}>
          <option value="">All outcomes</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {o.replace(/_/g, " ")}
            </option>
          ))}
        </Select>
        <Select className="w-auto" value={type} onChange={(e) => (setType(e.target.value), setPage(1))}>
          <option value="">Phone + browser</option>
          <option value="outbound">Phone calls</option>
          <option value="web">Browser tests</option>
        </Select>
      </div>
      <Card>
        {error ? (
          <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="Couldn't load calls" description={error.message} />
        ) : !data ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : data.items.length === 0 ? (
          <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="No calls found" description="Test an agent or start a campaign — calls show up here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-zinc-100 text-left text-xs text-zinc-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Contact</th>
                  <th className="px-5 py-3 font-medium">Agent</th>
                  <th className="px-5 py-3 font-medium">Outcome</th>
                  <th className="hidden px-5 py-3 font-medium lg:table-cell">Summary</th>
                  <th className="px-5 py-3 text-right font-medium">Duration</th>
                  <th className="px-5 py-3 text-right font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {data.items.map((c) => (
                  <tr key={c.id} className="cursor-pointer hover:bg-zinc-50">
                    <td className="px-5 py-3">
                      <Link href={`/calls/${c.id}`} className="flex items-center gap-2">
                        {c.call_type === "web" ? <Globe className="h-4 w-4 text-zinc-400" /> : <PhoneOutgoing className="h-4 w-4 text-zinc-400" />}
                        <span>
                          <span className="block font-medium">{c.contact_name ?? c.to_phone ?? "Unknown"}</span>
                          <span className="block text-xs text-zinc-500">{c.campaign_name ?? (c.call_type === "web" ? "Browser test" : c.to_phone)}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-5 py-3 text-zinc-600">{c.agent_name ?? "—"}</td>
                    <td className="px-5 py-3">
                      <OutcomeBadge outcome={c.outcome} status={c.status} />
                    </td>
                    <td className="hidden max-w-sm truncate px-5 py-3 text-xs text-zinc-500 lg:table-cell">{c.summary ?? "—"}</td>
                    <td className="px-5 py-3 text-right text-zinc-600">{formatDuration(c.duration_seconds)}</td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-zinc-500">{formatDateTime(c.started_at)}</td>
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
