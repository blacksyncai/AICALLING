"use client";

import { ListChecks, PhoneIncoming, PhoneOutgoing } from "lucide-react";
import { Badge, Input, Select, Toggle } from "@/components/ui";
import type { BuilderCatalog, DraftData, Followup, UseCase } from "@/lib/builder";
import { Collapsible, OptionCard, Segmented, StepTitle } from "./parts";

type Goal = NonNullable<DraftData["goal"]>;
type Direction = NonNullable<Goal["direction"]>;

export function useCasesFor(catalog: BuilderCatalog | undefined, industry: string | undefined): UseCase[] {
  if (!catalog) return [];
  return catalog.use_cases[industry ?? ""] ?? catalog.use_cases.other ?? [];
}

export function defaultAnswers(uc: UseCase): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (const f of uc.followups ?? []) {
    if (f.default !== undefined) out[f.key] = f.default;
    else if (f.type === "boolean") out[f.key] = false;
    else if (f.type === "choice") out[f.key] = f.options?.[0] ?? "";
    else out[f.key] = "";
  }
  return out;
}

export function StepGoal({
  goal,
  onChange,
  catalog,
  industry,
  showErrors,
}: {
  goal: Goal;
  onChange: (next: Goal) => void;
  catalog: BuilderCatalog | undefined;
  industry: string | undefined;
  showErrors: boolean;
}) {
  const all = useCasesFor(catalog, industry);
  const direction = goal.direction;
  const visible = direction ? all.filter((u) => direction === "both" || u.direction === direction) : [];
  const selected = all.find((u) => u.key === goal.use_case);
  const answers = goal.answers ?? {};

  function setDirection(d: Direction) {
    const keep = selected && (d === "both" || selected.direction === d);
    onChange({ ...goal, direction: d, ...(keep ? {} : { use_case: undefined, answers: {} }) });
  }

  function pick(uc: UseCase) {
    if (uc.key === goal.use_case) return;
    onChange({ ...goal, use_case: uc.key, answers: defaultAnswers(uc) });
  }

  return (
    <div>
      <StepTitle title="What should your agent do?" description="Pick the job that matters most. You can fine-tune everything later." />

      <div className="space-y-6">
        <div>
          <span className="mb-1.5 block text-xs font-medium text-zinc-700">Calls your agent will handle</span>
          <Segmented<Direction>
            label="Call direction"
            value={direction}
            onChange={setDirection}
            options={[
              { value: "outbound", label: "Calls out" },
              { value: "inbound", label: "Answers calls" },
              { value: "both", label: "Both" },
            ]}
          />
          <p className="mt-1.5 text-xs text-zinc-500">
            {direction === "outbound"
              ? "Your agent reaches out to leads and customers."
              : direction === "inbound"
                ? "Your agent picks up when people call your business."
                : direction === "both"
                  ? "Your agent makes calls and answers them."
                  : "Choose one to see what your agent can do."}
          </p>
          {showErrors && !direction && <span className="mt-1 block text-xs text-red-600">Please choose one.</span>}
        </div>

        {direction && (
          <div>
            <span className="mb-1.5 block text-xs font-medium text-zinc-700">Main goal</span>
            {!catalog ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-16 animate-pulse rounded-xl bg-zinc-100" />
                ))}
              </div>
            ) : visible.length === 0 ? (
              <p className="text-sm text-zinc-500">No ready-made goals for this yet — go back and pick &quot;Other&quot; as your industry.</p>
            ) : (
              <div role="radiogroup" aria-label="Main goal" className="space-y-2">
                {visible.map((uc) => (
                  <OptionCard
                    key={uc.key}
                    selected={goal.use_case === uc.key}
                    onClick={() => pick(uc)}
                    icon={uc.direction === "inbound" ? <PhoneIncoming className="h-4 w-4" /> : <PhoneOutgoing className="h-4 w-4" />}
                    title={uc.label}
                    badge={direction === "both" ? <Badge tone="gray">{uc.direction === "inbound" ? "Answers" : "Calls out"}</Badge> : undefined}
                    description={uc.description}
                  />
                ))}
              </div>
            )}
            {showErrors && !goal.use_case && <span className="mt-1 block text-xs text-red-600">Please pick a goal.</span>}
          </div>
        )}

        {selected && (
          <div key={selected.key} className="space-y-4 transition duration-300 starting:translate-y-1 starting:opacity-0">
            {(selected.followups ?? []).length > 0 && (
              <div className="space-y-3">
                <span className="block text-xs font-medium text-zinc-700">A few details</span>
                {selected.followups.map((f) => (
                  <FollowupInput key={f.key} f={f} value={answers[f.key]} onChange={(v) => onChange({ ...goal, answers: { ...answers, [f.key]: v } })} />
                ))}
              </div>
            )}

            <Collapsible
              title={
                <>
                  <ListChecks className="h-4 w-4 text-zinc-400" /> What the agent will cover
                </>
              }
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <PreviewList title="Goals on each call" items={selected.objectives} />
                <PreviewList title="Questions it will ask" items={selected.qualification_questions} />
              </div>
            </Collapsible>
          </div>
        )}
      </div>
    </div>
  );
}

function PreviewList({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</h4>
      <ul className="space-y-1">
        {items.map((t) => (
          <li key={t} className="flex gap-2 text-sm text-zinc-700">
            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand-500" />
            {t}
          </li>
        ))}
      </ul>
    </div>
  );
}

function FollowupInput({ f, value, onChange }: { f: Followup; value: string | boolean | undefined; onChange: (v: string | boolean) => void }) {
  if (f.type === "boolean") {
    return <Toggle label={f.label} checked={value === true} onChange={onChange} />;
  }
  if (f.type === "choice") {
    const options = f.options ?? [];
    const short = options.length <= 3 && options.every((o) => o.length <= 22);
    return (
      <div>
        <span className="mb-1.5 block text-sm text-zinc-800">{f.label}</span>
        {short ? (
          <Segmented<string> label={f.label} value={typeof value === "string" ? value : undefined} onChange={onChange} options={options.map((o) => ({ value: o, label: o }))} />
        ) : (
          <Select aria-label={f.label} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)}>
            {options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </Select>
        )}
      </div>
    );
  }
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm text-zinc-800">{f.label}</span>
      <Input value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
