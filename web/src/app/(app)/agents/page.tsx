"use client";

import { Bot, Copy, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { NewAgentChooser } from "@/components/builder/NewAgentChooser";
import { Badge, Button, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { del, fetcher, post } from "@/lib/api";
import type { Agent } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

function AgentCard({ agent, onChanged }: { agent: Agent; onChanged: () => void }) {
  const toast = useToast();
  const [menu, setMenu] = useState(false);

  return (
    <Card className="group relative flex flex-col p-5 transition hover:border-zinc-300 hover:shadow-sm">
      <Link href={`/agents/${agent.id}`} className="absolute inset-0 rounded-xl" aria-label={`Open ${agent.name}`} />
      <div className="flex items-start justify-between">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl brand-gradient text-white">
          <Bot className="h-5 w-5" />
        </span>
        <div className="relative z-10">
          <button onClick={() => setMenu((v) => !v)} className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" aria-label="Agent actions">
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {menu && (
            <div className="absolute right-0 top-8 w-40 rounded-lg border border-zinc-200 bg-white py-1 shadow-lg" onMouseLeave={() => setMenu(false)}>
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-zinc-50"
                onClick={async () => {
                  setMenu(false);
                  await post(`/api/agents/${agent.id}/duplicate`).catch((e) => toast(e.message, "error"));
                  onChanged();
                }}
              >
                <Copy className="h-4 w-4" /> Duplicate
              </button>
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50"
                onClick={async () => {
                  setMenu(false);
                  if (!confirm(`Delete "${agent.name}"? Call history is kept.`)) return;
                  await del(`/api/agents/${agent.id}`).catch((e) => toast(e.message, "error"));
                  onChanged();
                }}
              >
                <Trash2 className="h-4 w-4" /> Delete
              </button>
            </div>
          )}
        </div>
      </div>
      <h3 className="mt-4 font-semibold">{agent.name}</h3>
      <p className="mt-1 line-clamp-2 min-h-[2.5rem] text-sm text-zinc-500">{agent.description || "No description"}</p>
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-4 text-xs text-zinc-500">
        <Badge tone={agent.status === "active" ? "green" : "gray"}>{agent.status === "active" ? "Active" : "Paused"}</Badge>
        {agent.enable_booking && <Badge tone="blue">Booking</Badge>}
        {agent.transfer_number && <Badge tone="violet">Transfer</Badge>}
        <span className="ml-auto">
          {agent.stats?.calls ?? 0} calls · {timeAgo(agent.updated_at)}
        </span>
      </div>
    </Card>
  );
}

export default function AgentsPage() {
  const { data: agents, mutate, error } = useSWR<Agent[]>("/api/agents/", fetcher);
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Agents"
        description="Each agent is a voice persona with its own prompt, voice, knowledge and actions."
        action={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" /> New agent
          </Button>
        }
      />
      {error ? (
        <Card>
          <EmptyState icon={<Bot className="h-5 w-5" />} title="Couldn't load agents" description={error.message} />
        </Card>
      ) : !agents ? (
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      ) : agents.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Bot className="h-5 w-5" />}
            title="No agents yet"
            description="Tell us about your business and we'll build your first AI calling agent."
            action={
              <Button variant="primary" onClick={() => setOpen(true)}>
                <Plus className="h-4 w-4" /> New agent
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((a) => (
            <AgentCard key={a.id} agent={a} onChanged={() => mutate()} />
          ))}
        </div>
      )}
      <NewAgentChooser open={open} onClose={() => setOpen(false)} />
    </>
  );
}
