"use client";

import { Sparkles, Wand2, X } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Input, Modal } from "@/components/ui";
import { patch, post } from "@/lib/api";
import { sectionOrder } from "@/lib/builder";
import type { Agent } from "@/lib/types";
import { DiffView } from "./DiffView";
import { assemblePrompt } from "./prompt";

type Proposal = { summary: string; system_prompt: string; first_message: string; sections?: Record<string, string> | null };

const EXAMPLES = [
  "Make the opening more conversational",
  "Ask fewer qualification questions",
  "Focus more on booking appointments",
  "Use a softer approach with older leads",
];

/** "Improve with AI": ask for a change in plain words, review the diff, then apply. Never auto-applies. */
export function ImproveWithAI({
  agent,
  beforeImprove,
  onApplied,
}: {
  agent: Agent;
  /** Called before asking the AI — saves pending edits so the proposal is based on what you see. */
  beforeImprove: () => Promise<boolean>;
  onApplied: (updated: Agent) => void;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);

  const currentSections = agent.builder?.sections ?? null;

  async function ask(text = instruction) {
    const value = text.trim();
    if (!value) return;
    setInstruction(value);
    if (!(await beforeImprove())) return;
    setLoading(true);
    try {
      const res = await post<Proposal>(`/api/agent-builder/agents/${agent.id}/improve`, { instruction: value });
      setProposal({
        ...res,
        summary: res.summary ?? "",
        first_message: res.first_message ?? agent.first_message,
        system_prompt: res.system_prompt ?? agent.system_prompt,
      });
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }

  const changedSections =
    proposal?.sections && currentSections
      ? sectionOrder(agent.builder).filter(([k]) => (proposal.sections?.[k] ?? currentSections[k] ?? "") !== (currentSections[k] ?? ""))
      : [];
  const firstChanged = !!proposal && proposal.first_message !== agent.first_message;
  const useSectionView = !!proposal?.sections && !!currentSections;
  const promptChanged = !!proposal && (useSectionView ? changedSections.length > 0 : proposal.system_prompt !== agent.system_prompt);

  async function apply() {
    if (!proposal) return;
    setApplying(true);
    try {
      const body: Partial<Agent> = { first_message: proposal.first_message };
      if (proposal.sections && agent.builder) {
        const sections = { ...(agent.builder.sections ?? {}), ...proposal.sections };
        body.builder = { ...agent.builder, sections };
        body.system_prompt = assemblePrompt(sections, sectionOrder(agent.builder));
      } else {
        body.system_prompt = proposal.system_prompt;
      }
      const updated = await patch<Agent>(`/api/agents/${agent.id}`, body);
      onApplied(updated);
      toast("Changes applied");
      setProposal(null);
      setInstruction("");
      setOpen(false);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setApplying(false);
    }
  }

  return (
    <>
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100"
        >
          <Wand2 className="h-3.5 w-3.5" /> Improve with AI
        </button>
      ) : (
        <div className="w-full rounded-xl border border-brand-200 bg-brand-50/60 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-brand-700">
              <Wand2 className="h-3.5 w-3.5" /> Improve with AI
            </span>
            <button onClick={() => setOpen(false)} className="rounded p-1 text-zinc-400 hover:bg-white hover:text-zinc-700" aria-label="Close improve with AI">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <form
            className="flex flex-col gap-2 sm:flex-row"
            onSubmit={(e) => {
              e.preventDefault();
              ask();
            }}
          >
            <Input
              autoFocus
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Describe what you'd like to change…"
              aria-label="What should the AI change?"
              className="bg-white"
            />
            <Button variant="primary" type="submit" loading={loading} disabled={!instruction.trim()} className="shrink-0">
              {!loading && <Sparkles className="h-4 w-4" />} Suggest changes
            </Button>
          </form>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                disabled={loading}
                onClick={() => ask(ex)}
                className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-[11px] text-zinc-600 hover:border-brand-200 hover:text-brand-700 disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-zinc-500">You&apos;ll review every change before anything is saved.</p>
        </div>
      )}

      <Modal open={!!proposal} onClose={() => !applying && setProposal(null)} title="Review suggested changes" wide>
        {proposal && (
          <div className="space-y-4">
            <div className="rounded-lg bg-zinc-50 px-3 py-2.5 text-sm text-zinc-700">
              <span className="font-medium text-zinc-900">What changes: </span>
              {proposal.summary || "The AI updated your script."}
              <div className="mt-1 text-xs text-zinc-500">Request: “{instruction}”</div>
            </div>
            {!firstChanged && !promptChanged && <p className="text-sm text-zinc-500">The AI didn&apos;t suggest any changes. Try a more specific request.</p>}
            {firstChanged && (
              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">First message</h3>
                <DiffView before={agent.first_message} after={proposal.first_message} />
              </section>
            )}
            {useSectionView
              ? changedSections.map(([k, label]) => (
                  <section key={k}>
                    <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">{label}</h3>
                    <DiffView before={currentSections?.[k] ?? ""} after={proposal.sections?.[k] ?? ""} className="max-h-72 overflow-y-auto" />
                  </section>
                ))
              : promptChanged && (
                  <section>
                    <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">Script</h3>
                    <DiffView before={agent.system_prompt} after={proposal.system_prompt} className="max-h-96 overflow-y-auto" />
                  </section>
                )}
            <div className="flex flex-col-reverse gap-2 border-t border-zinc-100 pt-4 sm:flex-row sm:justify-end">
              <Button onClick={() => setProposal(null)} disabled={applying}>
                Discard
              </Button>
              <Button variant="primary" onClick={apply} loading={applying} disabled={!firstChanged && !promptChanged}>
                Apply changes
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}
