"use client";

import { History, RotateCcw } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Modal, Notice, Spinner } from "@/components/ui";
import { api, fetcher, post } from "@/lib/api";
import type { AgentVersionFull, AgentVersionSummary } from "@/lib/builder";
import type { Agent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DiffView } from "./DiffView";

const SOURCE: Record<string, string> = {
  generated: "Generated",
  edited: "Edited",
  improved: "Improved with AI",
  regenerated: "Section regenerated",
  restored: "Restored",
  original: "Before edits",
};

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}

/** "History" button + modal: every saved version of the prompt, a diff against the current one, and restore. */
export function VersionHistory({ agent, dirty, onRestored }: { agent: Agent; dirty: boolean; onRestored: (a: Agent) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<AgentVersionFull | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);
  const url = `/api/agents/${agent.id}/versions`;
  // Keyed on updated_at so the list refreshes after every save.
  const { data, isLoading } = useSWR<{ versions: AgentVersionSummary[] }>(open ? [url, agent.updated_at] : null, ([u]: [string]) => fetcher(u));
  const versions = data?.versions ?? [];

  async function pick(v: AgentVersionSummary) {
    setLoadingId(v.id);
    try {
      setSelected(await api<AgentVersionFull>(`${url}/${v.id}`));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setLoadingId(null);
    }
  }

  async function restore() {
    if (!selected) return;
    const msg = dirty
      ? `Restore version ${selected.version}? Your unsaved changes will be discarded.`
      : `Restore version ${selected.version}? Your current prompt stays in the history.`;
    if (!window.confirm(msg)) return;
    setRestoring(true);
    try {
      const updated = await post<Agent>(`${url}/${selected.id}/restore`, {});
      onRestored(updated);
      toast(`Restored version ${selected.version}`);
      setSelected(null);
      setOpen(false);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setRestoring(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800"
      >
        <History className="h-3.5 w-3.5" /> History
      </button>
      <Modal open={open} onClose={() => { setOpen(false); setSelected(null); }} title="Prompt history" wide>
        <div className="space-y-4">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : versions.length === 0 ? (
            <p className="text-sm text-zinc-500">No saved versions yet. Each time you save changes to the prompt, a version is kept here.</p>
          ) : (
            <ul className="max-h-60 divide-y divide-zinc-100 overflow-y-auto rounded-xl border border-zinc-200">
              {versions.map((v, i) => (
                <li key={v.id}>
                  <button
                    onClick={() => pick(v)}
                    className={cn("flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-left text-sm hover:bg-zinc-50", selected?.id === v.id && "bg-brand-50/60")}
                  >
                    <span className="font-medium tabular-nums text-zinc-900">v{v.version}</span>
                    <span className="text-zinc-700">{SOURCE[v.source] ?? v.source}</span>
                    {i === 0 && <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-600">Latest</span>}
                    <span className="ml-auto text-xs tabular-nums text-zinc-400">
                      {v.words.toLocaleString()} words · {when(v.created_at)}
                    </span>
                    {loadingId === v.id && <Spinner />}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {selected && (
            <div className="space-y-2">
              <div className="text-xs font-medium text-zinc-700">
                Changes from version {selected.version} to the current saved prompt
              </div>
              {selected.system_prompt === agent.system_prompt && selected.first_message === agent.first_message ? (
                <Notice tone="blue">This version matches the current prompt.</Notice>
              ) : (
                <DiffView
                  before={`First message: ${selected.first_message}\n\n${selected.system_prompt}`}
                  after={`First message: ${agent.first_message}\n\n${agent.system_prompt}`}
                  className="max-h-[50vh] overflow-y-auto"
                />
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
                  Close
                </Button>
                <Button size="sm" onClick={restore} loading={restoring}>
                  <RotateCcw className="h-3.5 w-3.5" /> Restore this version
                </Button>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}
