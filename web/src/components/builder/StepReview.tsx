"use client";

import { AlertCircle, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Button, Notice } from "@/components/ui";
import type { BuilderCatalog, BusinessProfile, DraftData } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { useCasesFor } from "./StepGoal";
import { LANGUAGES, type VoicesResponse } from "./StepPersonality";
import { StepTitle, displayHost } from "./parts";

const DIRECTION = { outbound: "Calls out", inbound: "Answers calls", both: "Calls out and answers calls" } as const;

export function StepReview({
  data,
  catalog,
  profile,
  voices,
  onEdit,
}: {
  data: DraftData;
  catalog: BuilderCatalog | undefined;
  profile: BusinessProfile | null;
  voices: VoicesResponse | undefined;
  onEdit: (step: number) => void;
}) {
  const b = data.business ?? {};
  const g = data.goal ?? {};
  const be = data.behavior ?? {};
  const industry = catalog?.industries.find((i) => i.key === b.industry)?.label ?? b.industry;
  const useCase = useCasesFor(catalog, b.industry).find((u) => u.key === g.use_case)?.label ?? g.use_case;
  const allVoices = [...(voices?.featured ?? []), ...(voices?.voices ?? [])];
  const voice = allVoices.find((v) => v.id === be.voice_id)?.name ?? (be.voice_id ? "Selected voice" : "Default voice");
  const language = LANGUAGES.find(([k]) => k === (be.language ?? "en"))?.[1];
  const style = catalog?.styles.find((s) => s.key === be.style)?.label;
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
          <Row label="Calls" value={g.direction ? DIRECTION[g.direction] : undefined} />
          <Row label="Main goal" value={useCase} />
        </Group>
        <Group title="Personality" onEdit={() => onEdit(3)}>
          <Row label="Agent name" value={be.agent_name} />
          <Row label="Voice" value={`${voice}${language ? ` · ${language}` : ""}`} />
          {style && <Row label="Style" value={style} />}
          <Row label="On the call" value={actions.join(" · ") || "Conversation only"} />
        </Group>
        <Group title="Tools" onEdit={() => onEdit(4)}>
          <Row label="Connected" value={tools.length ? tools.join(", ") : "None for now"} />
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

const LINES = [
  "Reading your business knowledge",
  "Writing your agent's introduction",
  "Planning how the conversation should flow",
  "Preparing answers to common questions",
  "Getting ready for objections",
  "Setting up booking and transfers",
  "Adding disclosure and compliance details",
  "Final checks",
];

export function Generating() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((n) => Math.min(n + 1, LINES.length - 1)), 4000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="flex flex-col items-center px-4 py-14 text-center" role="status" aria-live="polite">
      <div className="relative">
        <span className="absolute inset-0 animate-ping rounded-2xl bg-brand-500/20" />
        <span className="relative flex h-14 w-14 items-center justify-center rounded-2xl brand-gradient text-white shadow-lg">
          <Sparkles className="h-6 w-6 animate-pulse" />
        </span>
      </div>
      <h2 className="mt-6 font-display text-xl font-semibold tracking-tight text-zinc-900">Building your agent</h2>
      <p key={i} className="mt-2 h-5 text-sm text-zinc-500 transition duration-500 starting:translate-y-1 starting:opacity-0">
        {LINES[i]}…
      </p>
      <div className="mt-6 h-1 w-56 max-w-full overflow-hidden rounded-full bg-zinc-100">
        <div
          className="h-full rounded-full bg-brand-600 transition-all duration-[4000ms] ease-out"
          style={{ width: `${Math.min(95, 10 + (i / (LINES.length - 1)) * 85)}%` }}
        />
      </div>
      <p className="mt-4 text-xs text-zinc-400">This usually takes under a minute.</p>
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
