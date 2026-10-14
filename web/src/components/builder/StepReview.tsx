"use client";

import { AlertCircle, Check, Loader2, RotateCcw, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { Button, Notice } from "@/components/ui";
import { CUSTOM_USE_CASE, type BuilderCatalog, type BusinessProfile, type DraftData, type Generation } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { customDescription, presetKeys, selectedKeys, useCasesFor } from "./goal";
import { decidesLater, recommendedRows } from "./StepFineTune";
import { LANGUAGES, useModelName, type VoicesResponse } from "./StepPersonality";
import { StepTitle, displayHost } from "./parts";

const REPRESENT: Record<string, string> = {
  team_member: "As part of your team",
  ai_assistant: "As your AI assistant",
  custom: "With your own introduction",
};

const DIRECTION = { outbound: "Calls out", inbound: "Answers calls", both: "Calls out and answers calls" } as const;

export function StepReview({
  data,
  catalog,
  profile,
  voices,
  onEdit,
  bookingLikely,
  references,
}: {
  data: DraftData;
  catalog: BuilderCatalog | undefined;
  profile: BusinessProfile | null;
  voices: VoicesResponse | undefined;
  onEdit: (step: number) => void;
  bookingLikely: boolean;
  references: number;
}) {
  const b = data.business ?? {};
  const g = data.goal ?? {};
  const be = data.behavior ?? {};
  const modelName = useModelName(be.llm_model);
  const industry = catalog?.industries.find((i) => i.key === b.industry)?.label ?? b.industry;
  const ucs = useCasesFor(catalog, b.industry);
  const keys = selectedKeys(g);
  const goals = presetKeys(g).map((k) => ucs.find((u) => u.key === k)?.label ?? k);
  const own = keys.includes(CUSTOM_USE_CASE) || goals.length === 0 ? customDescription(g).trim() : "";
  const answered = (g.assistant ?? []).filter((i) => i.answer || i.delegated).length;
  const later = decidesLater(be);
  const allVoices = [...(voices?.featured ?? []), ...(voices?.voices ?? [])];
  const voice = allVoices.find((v) => v.id === be.voice_id)?.name ?? (be.voice_id ? "Selected voice" : "Recommended voice");
  const language = LANGUAGES.find(([k]) => k === (be.language ?? "en"))?.[1];
  const style = be.style ? catalog?.styles.find((s) => s.key === be.style)?.label : "Matches your goal";
  const tools = (data.integrations?.selected ?? []).map((k) => catalog?.integrations.find((i) => i.key === k)?.label ?? k);

  const knowledge =
    profile?.status === "analyzing"
      ? "Still reading your website"
      : profile && profile.item_count > 0
        ? `${profile.item_count} facts${profile.website ? ` from ${displayHost(profile.website)}` : ""}${profile.review_count ? ` · ${profile.review_count} to double-check` : ""}`
        : "None added — your agent will stick to the basics";

  const actions = [
    be.booking ? "Books appointments" : null,
    be.transfer_number ? `Transfers to ${be.transfer_number}` : null,
    be.callback !== false ? "Offers callbacks" : null,
    be.ai_disclosure !== false ? "Says it's an AI" : null,
  ].filter(Boolean);

  return (
    <div>
      <StepTitle title="Review your agent" description="Check the details, then we'll write your agent's script and settings." />
      <div className="space-y-3">
        <Group title="Business" onEdit={() => onEdit(1)}>
          <Row label="Company" value={b.name} />
          <Row label="Industry" value={industry} />
          <Row label="Knowledge" value={knowledge} />
        </Group>
        <Group title="Goal" onEdit={() => onEdit(2)}>
          <Row label="Calls" value={DIRECTION[g.direction ?? "outbound"]} />
          {goals.length > 0 && <Row label={goals.length > 1 ? "Goals" : "Main goal"} value={goals.join(" · ")} />}
          {own && <Row label="Your words" value={<span className="line-clamp-3">{own}</span>} />}
          {g.extra_instructions?.trim() && !own && <Row label="Specifics" value={<span className="line-clamp-2">{g.extra_instructions.trim()}</span>} />}
          {answered > 0 && <Row label="AI follow-ups" value={`${answered} answered`} />}
        </Group>
        <Group title="Agent" onEdit={() => onEdit(3)}>
          <Row label="Name" value={be.agent_name?.trim() || "AI will pick one"} />
          <Row label="Introduces itself" value={REPRESENT[be.representation ?? "ai_assistant"]} />
          {later ? (
            <>
              <Row label="Call settings" value="Recommended — change anytime in the agent editor" />
              {recommendedRows(catalog, bookingLikely)
                .slice(0, 2)
                .map(([k, v]) => (
                  <Row key={k} label={k} value={v} />
                ))}
            </>
          ) : (
            <>
              {style && <Row label="Style" value={style} />}
              <Row label="On the call" value={actions.join(" · ") || "Conversation only"} />
              <Row label="Tools" value={tools.length ? tools.join(", ") : "None for now"} />
            </>
          )}
        </Group>
        <Group title="References" onEdit={() => onEdit(4)}>
          <Row label="Your scripts" value={references > 0 ? `${references} added` : "None — skipped"} />
        </Group>
        <Group title="Voice" onEdit={() => onEdit(5)}>
          <Row label="Voice" value={`${voice}${language ? ` · ${language}` : ""}`} />
          <Row label="AI model" value={modelName.charAt(0).toUpperCase() + modelName.slice(1)} />
        </Group>
      </div>
    </div>
  );
}

function Group({ title, onEdit, children }: { title: string; onEdit: () => void; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</h3>
        <button
          type="button"
          onClick={onEdit}
          className="rounded-md px-2 py-0.5 text-xs font-medium text-brand-700 hover:bg-brand-50 focus-visible:outline-2 focus-visible:outline-brand-500"
          aria-label={`Edit ${title.toLowerCase()}`}
        >
          Edit
        </button>
      </div>
      <dl className="divide-y divide-zinc-50 px-4">{children}</dl>
    </section>
  );
}

function Row({ label, value }: { label: string; value: ReactNode | undefined }) {
  return (
    <div className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-4">
      <dt className="shrink-0 text-xs text-zinc-500 sm:w-28 sm:pt-0.5">{label}</dt>
      <dd className={cn("min-w-0 break-words text-sm", value ? "text-zinc-900" : "text-zinc-400")}>{value || "Not set"}</dd>
    </div>
  );
}

/** Live progress of the background generation job (stages come from the server). */
export function Generating({ generation }: { generation: Generation | null }) {
  const stages = generation?.stages ?? [];
  const current = Math.max(0, stages.findIndex((s) => s.key === generation?.stage));
  return (
    <div className="flex flex-col items-center px-4 py-12 text-center" role="status" aria-live="polite">
      <div className="relative">
        <span className="absolute inset-0 animate-ping rounded-2xl bg-brand-500/20" />
        <span className="relative flex h-14 w-14 items-center justify-center rounded-2xl brand-gradient text-white shadow-lg">
          <Sparkles className="h-6 w-6 animate-pulse" />
        </span>
      </div>
      <h2 className="mt-6 font-display text-xl font-semibold tracking-tight text-zinc-900">Your agent is coming together</h2>
      <p className="mt-1 text-sm text-zinc-500">Writing the script, conversation flow and call rules from your answers.</p>
      <ol className="mt-5 w-full max-w-xs space-y-2 text-left">
        {stages.map((s, i) => (
          <li key={s.key} className="flex items-center gap-2.5 text-sm">
            {i < current ? (
              <Check className="h-4 w-4 shrink-0 text-emerald-600" />
            ) : i === current ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand-600" />
            ) : (
              <span className="h-4 w-4 shrink-0 rounded-full border border-zinc-300" />
            )}
            <span className={cn(i <= current ? "text-zinc-900" : "text-zinc-400")}>{s.label}</span>
          </li>
        ))}
      </ol>
      <p className="mt-5 text-xs text-zinc-400">A full script takes one to three minutes. You can leave this page — we&apos;ll keep going.</p>
    </div>
  );
}

export function GenerateError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mt-4">
      <Notice tone="red">
        <span className="flex flex-wrap items-start gap-2">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1">We couldn&apos;t build your agent. {message}</span>
          <Button size="sm" onClick={onRetry}>
            <RotateCcw className="h-3.5 w-3.5" /> Try again
          </Button>
        </span>
      </Notice>
    </div>
  );
}
