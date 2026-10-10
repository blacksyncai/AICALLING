"use client";

import { Clock, Megaphone, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { describeWindow } from "@/components/campaigns/CallingRules";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, PageHeader, Select, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { Agent, Campaign } from "@/lib/types";
import { CAMPAIGN_TONE, timeAgo } from "@/lib/utils";



function NewCampaignModal({ open, onClose, agents }: { open: boolean; onClose: () => void; agents: Agent[] }) {
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const c = await post<Campaign>("/api/campaigns/", { name, agent_id: agentId || agents[0]?.id || null });
      router.push(`/campaigns/${c.id}`);
    } catch (err) {
      toast((err as Error).message, "error");
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New campaign">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Campaign name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Q4 outbound — SaaS founders" required autoFocus />
        </Field>
        <Field label="Agent" hint="The agent that will place every call in this campaign.">
          <Select value={agentId || agents[0]?.id || ""} onChange={(e) => setAgentId(e.target.value)} required>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </Field>
        {agents.length === 0 && (
          <p className="text-xs text-amber-700">
            You need an agent first — <Link href="/agents" className="underline">create one</Link>.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!name.trim() || agents.length === 0}>
            Create & add leads
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function CampaignsPage() {
  const { data, error } = useSWR<{ campaigns: Campaign[] }>("/api/campaigns/", fetcher, { refreshInterval: 10000 });
  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const [open, setOpen] = useState(false);
  const agentName = (id: string | null) => agents?.find((a) => a.id === id)?.name ?? "—";

  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Upload a list of contacts and let an agent call through it."
        action={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" /> New campaign
          </Button>
        }
      />
      <Card>
        {error ? (
          <EmptyState icon={<Megaphone className="h-5 w-5" />} title="Couldn't load campaigns" description={error.message} />
        ) : !data ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : data.campaigns.length === 0 ? (
          <EmptyState
            icon={<Megaphone className="h-5 w-5" />}
            title="No campaigns yet"
            description="Create a campaign, import a CSV of contacts, pick an agent and hit start."
            action={
              <Button variant="primary" onClick={() => setOpen(true)}>
                <Plus className="h-4 w-4" /> New campaign
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-zinc-100 text-left text-xs text-zinc-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Campaign</th>
                  <th className="px-5 py-3 font-medium">Agent</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Progress</th>
                  <th className="px-5 py-3 text-right font-medium">Qualified</th>
                  <th className="px-5 py-3 text-right font-medium">Booked</th>
                  <th className="px-5 py-3 text-right font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {data.campaigns.map((c) => {
                  const pct = c.total_targets ? Math.min(100, Math.round((c.total_dialed / c.total_targets) * 100)) : 0;
                  return (
                    <tr key={c.id} className="hover:bg-zinc-50">
                      <td className="px-5 py-3">
                        <Link href={`/campaigns/${c.id}`} className="font-medium hover:text-brand-700">
                          {c.name}
                        </Link>
                        {c.call_window_start && c.call_days && (
                          <div className="mt-0.5 flex items-center gap-1 text-xs text-zinc-500">
                            <Clock className="h-3 w-3 shrink-0" />
                            <span className="truncate">
                              {describeWindow(c)}
                              {c.max_attempts > 1 ? ` · up to ${c.max_attempts} tries` : ""}
                            </span>
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3 text-zinc-600">{agentName(c.agent_id)}</td>
                      <td className="px-5 py-3">
                        <Badge tone={CAMPAIGN_TONE[c.status]}>{c.status}</Badge>
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 rounded-full bg-zinc-100">
                            <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="text-xs text-zinc-500">
                            {c.total_dialed}/{c.total_targets}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-right">{c.total_qualified}</td>
                      <td className="px-5 py-3 text-right">{c.total_booked}</td>
                      <td className="px-5 py-3 text-right text-xs text-zinc-500">{timeAgo(c.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <NewCampaignModal open={open} onClose={() => setOpen(false)} agents={agents ?? []} />
    </>
  );
}
