"use client";

import { Clock, Megaphone, PhoneIncoming, PhoneOutgoing, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { describeWindow } from "@/components/campaigns/CallingRules";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, PageHeader, Select, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { Agent, Campaign, MyPhoneNumbers } from "@/lib/types";
import { CAMPAIGN_TONE, timeAgo } from "@/lib/utils";



function NewCampaignModal({ open, onClose, agents }: { open: boolean; onClose: () => void; agents: Agent[] }) {
  const router = useRouter();
  const toast = useToast();
  const [kind, setKind] = useState<"outbound" | "inbound">("outbound");
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [numberId, setNumberId] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: phones } = useSWR<MyPhoneNumbers>(open ? "/api/phone-numbers" : null, fetcher);
  const numbers = phones?.numbers ?? [];
  const noNumber = kind === "inbound" && !!phones && numbers.length === 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const c = await post<Campaign>("/api/campaigns/", {
        name, agent_id: agentId || agents[0]?.id || null, direction: kind,
        ...(kind === "inbound" ? { phone_number_id: numberId || numbers[0]?.id } : {}),
      });
      router.push(`/campaigns/${c.id}`);
    } catch (err) {
      toast((err as Error).message, "error");
      setBusy(false);
    }
  }

  const tile = (on: boolean) =>
    `flex flex-1 items-start gap-3 rounded-xl border p-3 text-left transition-colors ${on ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-zinc-200 hover:border-zinc-300"}`;

  return (
    <Modal open={open} onClose={onClose} title="New campaign">
      <form onSubmit={submit} className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <button type="button" className={tile(kind === "outbound")} onClick={() => setKind("outbound")}>
            <PhoneOutgoing className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
            <span>
              <span className="block text-sm font-medium text-zinc-900">Outbound</span>
              <span className="block text-xs text-zinc-500">Your agent calls through a list of contacts.</span>
            </span>
          </button>
          <button type="button" className={tile(kind === "inbound")} onClick={() => setKind("inbound")}>
            <PhoneIncoming className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
            <span>
              <span className="block text-sm font-medium text-zinc-900">Inbound</span>
              <span className="block text-xs text-zinc-500">Your agent answers calls to your number.</span>
            </span>
          </button>
        </div>
        <Field label="Campaign name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={kind === "inbound" ? "Front desk — after hours" : "Q4 outbound — expired listings"} required autoFocus />
        </Field>
        <Field label="Agent" hint={kind === "inbound" ? "The agent that answers every call." : "The agent that will place every call in this campaign."}>
          <Select value={agentId || agents[0]?.id || ""} onChange={(e) => setAgentId(e.target.value)} required>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </Field>
        {kind === "inbound" &&
          (noNumber ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <div className="font-medium">You need your own phone number for inbound.</div>
              <p className="mt-0.5 text-xs">
                Calls have to come in somewhere — the shared platform line can&apos;t answer for you. Get a number, then forward your business line to it (we&apos;ll show you how for
                Verizon, AT&amp;T, T-Mobile and more).
              </p>
              <Link href="/phone-numbers" className="mt-2 inline-flex text-xs font-semibold underline">
                Get a phone number →
              </Link>
            </div>
          ) : (
            <Field label="Number to answer">
              <Select value={numberId || numbers[0]?.id || ""} onChange={(e) => setNumberId(e.target.value)} required>
                {numbers.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.number}
                    {n.label ? ` · ${n.label}` : ""}
                  </option>
                ))}
              </Select>
            </Field>
          ))}
        {agents.length === 0 && (
          <p className="text-xs text-amber-700">
            You need an agent first — <Link href="/agents" className="underline">create one</Link>.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!name.trim() || agents.length === 0 || noNumber || (kind === "inbound" && !phones)}>
            {kind === "inbound" ? "Create inbound campaign" : "Create & add leads"}
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
        description="Outbound: an agent calls through your list. Inbound: an agent answers your number."
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
                        {c.direction === "inbound" && (
                          <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-blue-50 px-1.5 py-0.5 align-middle text-[10px] font-medium text-blue-700">
                            <PhoneIncoming className="h-3 w-3" /> Inbound
                          </span>
                        )}
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
