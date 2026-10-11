"use client";

import { ArrowRight, History, Settings2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Modal, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { AgentDraft } from "@/lib/builder";
import type { Agent } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";
import { STEPS, resumeStep } from "./parts";

export function NewAgentChooser({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const { data } = useSWR<{ drafts: AgentDraft[] }>(open ? "/api/agent-builder/drafts" : null, fetcher, { shouldRetryOnError: false });
  const drafts = (data?.drafts ?? []).filter((d) => d.agent_id == null).slice(0, 2);

  async function createBlank() {
    setCreating(true);
    try {
      const agent = await post<Agent>("/api/agents/", { template: "blank" });
      router.push(`/agents/${agent.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      setCreating(false);
    }
  }

  const card =
    "group relative flex w-full items-start gap-3 rounded-xl border p-4 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500";

  return (
    <Modal open={open} onClose={onClose} title="Create an agent">
      <div className="space-y-2.5">
        <Link href="/agents/new" className={cn(card, "border-brand-200 bg-brand-50/40 hover:border-brand-500 hover:bg-brand-50/70")}>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg brand-gradient text-white">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900">
              Build with AI <Badge tone="brand">Recommended</Badge>
            </span>
            <span className="mt-0.5 block text-xs text-zinc-600">Pick a specialty, a voice and a mission. We&apos;ll do the rest.</span>
          </span>
          <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-brand-600 transition-transform group-hover:translate-x-0.5" />
        </Link>

        <button type="button" onClick={createBlank} disabled={creating} className={cn(card, "border-zinc-200 bg-white hover:border-zinc-300 hover:bg-zinc-50 disabled:opacity-70")}>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600">
            {creating ? <Spinner className="h-4 w-4" /> : <Settings2 className="h-4 w-4" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-zinc-900">Create from scratch</span>
            <span className="mt-0.5 block text-xs text-zinc-500">Configure your agent manually, from the ground up.</span>
          </span>
        </button>
      </div>

      {drafts.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-1.5 text-xs font-medium text-zinc-500">Continue where you left off</h3>
          <ul className="divide-y divide-zinc-100 overflow-hidden rounded-lg border border-zinc-200">
            {drafts.map((d) => {
              const step = resumeStep(d.step, d.data); // older drafts used six steps
              return (
                <li key={d.id}>
                  <Link
                    href={`/agents/new?draft=${d.id}`}
                    className="flex items-center gap-3 px-3 py-2.5 text-sm hover:bg-zinc-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-500"
                  >
                    <History className="h-4 w-4 shrink-0 text-zinc-400" />
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium text-zinc-900">
                        {[d.data?.behavior?.agent_name?.trim(), d.data?.goal?.specialty?.label].filter(Boolean).join(" — ") ||
                          d.data?.business?.name?.trim() ||
                          "Untitled agent"}
                      </span>
                      <span className="text-zinc-500">
                        {" "}
                        · Step {step} of {STEPS.length}
                        {d.updated_at && ` · ${timeAgo(d.updated_at)}`}
                      </span>
                    </span>
                    <ArrowRight className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Modal>
  );
}
