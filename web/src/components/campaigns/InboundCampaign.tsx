"use client";

import { ArrowLeft, Hash, Pause, PhoneIncoming, Radio, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { ForwardingGuide } from "@/components/campaigns/ForwardingGuide";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Notice, Select } from "@/components/ui";
import { del, fetcher, patch, post } from "@/lib/api";
import type { Agent, Call, Campaign, MyPhoneNumbers } from "@/lib/types";
import { CAMPAIGN_TONE, formatDuration, timeAgo } from "@/lib/utils";

const pretty = (e164: string) => {
  const d = e164.replace(/\D/g, "").replace(/^1(?=\d{10}$)/, "");
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : e164;
};

/** An inbound campaign: one of the account's numbers, answered by an agent. */
export function InboundCampaign({ campaign, calls, agents, onChange }: { campaign: Campaign; calls: Call[]; agents: Agent[]; onChange: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const { data: phones } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher);
  const [busy, setBusy] = useState<string | null>(null);
  const number = phones?.numbers.find((n) => n.id === campaign.phone_number_id);
  const live = campaign.status === "running";

  const act = async (name: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(name);
    try {
      await fn();
      if (ok) toast(ok);
      onChange();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Link href="/campaigns" className="mb-4 inline-flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-3 w-3" /> Campaigns
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{campaign.name}</h1>
            <Badge tone="blue">
              <PhoneIncoming className="h-3 w-3" /> Inbound
            </Badge>
            <Badge tone={live ? "green" : CAMPAIGN_TONE[campaign.status]}>{live ? "answering" : campaign.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-zinc-500">
            {number ? (
              <>
                Calls to <span className="font-mono font-medium text-zinc-800">{pretty(number.number)}</span> are answered by{" "}
                {agents.find((a) => a.id === campaign.agent_id)?.name ?? "your agent"}
                {live ? "." : " once you go live."}
              </>
            ) : (
              "Pick a number below."
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {live ? (
            <Button onClick={() => void act("pause", () => post(`/api/campaigns/${campaign.id}/pause`), "Stopped answering")} loading={busy === "pause"}>
              <Pause className="h-4 w-4" /> Stop answering
            </Button>
          ) : (
            <Button
              variant="primary"
              loading={busy === "start"}
              disabled={!number || !campaign.agent_id || campaign.status === "cancelled"}
              onClick={() => void act("start", () => post(`/api/campaigns/${campaign.id}/start`), "Live — your agent is answering")}
            >
              <Radio className="h-4 w-4" /> Go live
            </Button>
          )}
          <Button
            variant="ghost"
            aria-label="Delete campaign"
            onClick={() => {
              if (confirm("Delete this inbound campaign? Calls to the number will stop being answered.")) void act("delete", () => del(`/api/campaigns/${campaign.id}`)).then(() => router.push("/campaigns"));
            }}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {!live && number && campaign.status !== "cancelled" && (
        <div className="mb-6">
          <Notice tone="amber">
            <strong>Not answering calls yet.</strong> Calls to {pretty(number.number)} (and anything forwarded to it) are turned away until you press{" "}
            <strong>Go live</strong>.
          </Notice>
        </div>
      )}
      {live && number && (
        <div className="mb-6">
          <Notice tone="green">
            Live — call or forward to <span className="font-mono">{pretty(number.number)}</span> and {agents.find((a) => a.id === campaign.agent_id)?.name ?? "your agent"} picks
            up.
          </Notice>
        </div>
      )}
      {phones && phones.numbers.length === 0 && (
        <div className="mb-6">
          <Notice tone="amber">
            Inbound campaigns need a number of your own.{" "}
            <Link href="/phone-numbers" className="font-medium underline">
              Get a phone number
            </Link>{" "}
            — then forward your existing business line to it, or give it out directly.
          </Notice>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card className="space-y-4 p-5">
          <div className="text-sm font-semibold text-zinc-900">Setup</div>
          <Field label="Number that gets answered">
            <Select
              value={campaign.phone_number_id ?? ""}
              onChange={(e) => void act("number", () => patch(`/api/campaigns/${campaign.id}`, { phone_number_id: e.target.value }), "Number updated")}
            >
              <option value="" disabled>
                Pick one of your numbers
              </option>
              {(phones?.numbers ?? []).map((n) => (
                <option key={n.id} value={n.id}>
                  {pretty(n.number)}
                  {n.label ? ` · ${n.label}` : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Agent that answers" hint="Tip: give it a first message like “Thanks for calling …, how can I help?”">
            <Select value={campaign.agent_id ?? ""} onChange={(e) => void act("agent", () => patch(`/api/campaigns/${campaign.id}`, { agent_id: e.target.value }), "Agent updated")}>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </Field>
          <ul className="space-y-1 text-xs text-zinc-500">
            <li>• Known callers are matched to your contacts, so the agent can greet them by name.</li>
            <li>• Calls use credits like outbound calls (AI time + phone line fee). With no credits, calls aren&apos;t answered.</li>
            <li>• One live inbound campaign per number — going live here pauses any other campaign on it.</li>
          </ul>
        </Card>

        <Card className="p-5">
          {number ? (
            <ForwardingGuide number={number.number} />
          ) : (
            <EmptyState icon={<Hash className="h-5 w-5" />} title="Pick a number first" description="Forwarding instructions show up here once a number is chosen." />
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader title="Calls answered" description={calls.length ? `${calls.length} recent` : undefined} />
        {calls.length === 0 ? (
          <EmptyState icon={<PhoneIncoming className="h-5 w-5" />} title="No calls yet" description="Answered calls show up here with the transcript, summary and recording." />
        ) : (
          <ul className="divide-y divide-zinc-100">
            {calls.map((c) => (
              <li key={c.id}>
                <Link href={`/calls/${c.id}`} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm hover:bg-zinc-50">
                  <PhoneIncoming className="h-4 w-4 text-zinc-400" />
                  <span className="min-w-0 flex-1 truncate font-medium text-zinc-800">{c.contact_name || (c.to_phone ? pretty(c.to_phone) : "Unknown caller")}</span>
                  {c.outcome && <OutcomeBadge outcome={c.outcome} />}
                  <span className="text-xs text-zinc-500">{c.duration_seconds ? formatDuration(c.duration_seconds) : "—"}</span>
                  <span className="text-xs text-zinc-400">{timeAgo(c.started_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
