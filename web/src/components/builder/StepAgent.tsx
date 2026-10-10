"use client";

import { Bot, PenLine, Users } from "lucide-react";
import { Field, Input, Textarea } from "@/components/ui";
import type { BuilderCatalog } from "@/lib/builder";
import { Chip, OptionCard, StepTitle } from "./parts";
import { StepFineTune } from "./StepFineTune";
import type { Behavior } from "./StepPersonality";

const NAMES = ["Maya", "Jordan", "Ava", "Sam", "Olivia", "Ethan"];

const REPRESENTATION = [
  { value: "team_member", title: "Part of your team", description: "Introduces itself as being with your company. Still honest that it's an AI when asked.", icon: <Users className="h-4 w-4" /> },
  { value: "ai_assistant", title: "Your AI assistant", description: "Says up front that it's your company's AI assistant.", icon: <Bot className="h-4 w-4" /> },
  { value: "custom", title: "My own introduction", description: "Write how it should introduce itself.", icon: <PenLine className="h-4 w-4" /> },
] as const;

/** Step 3: who the agent is (name, how it represents the business) plus optional call settings. */
export function StepAgent({
  behavior,
  onChange,
  businessName,
  ...fineTune
}: {
  behavior: Behavior;
  onChange: (patch: Partial<Behavior>) => void;
  businessName: string;
  catalog: BuilderCatalog | undefined;
  transferOn: boolean;
  setTransferOn: (v: boolean) => void;
  showErrors: boolean;
  tools: string[];
  onToolsChange: (next: string[]) => void;
  industry: string | undefined;
  bookingLikely: boolean;
}) {
  const rep = behavior.representation ?? "ai_assistant";
  const name = behavior.agent_name ?? "";
  const company = businessName || "your company";

  return (
    <div className="space-y-6">
      <StepTitle title="Your agent" description="Give it a name and decide how it introduces itself. Everything else has a sensible default." />

      <Field label="What should your agent be named?" hint="Any name works. Leave it empty and AI will pick one.">
        <Input value={name} onChange={(e) => onChange({ agent_name: e.target.value.slice(0, 40) })} placeholder="e.g. Maya" />
      </Field>
      <div className="-mt-3 flex flex-wrap gap-2" aria-label="Suggested names">
        {NAMES.map((n) => (
          <Chip key={n} selected={name === n} onClick={() => onChange({ agent_name: name === n ? "" : n })}>
            {n}
          </Chip>
        ))}
      </div>

      <div>
        <span className="mb-1.5 block text-xs font-medium text-zinc-700">How should it represent {company}?</span>
        <div role="radiogroup" aria-label="Representation" className="grid gap-2 sm:grid-cols-3">
          {REPRESENTATION.map((r) => (
            <OptionCard
              key={r.value}
              selected={rep === r.value}
              onClick={() => onChange({ representation: r.value })}
              title={r.title}
              description={r.description}
              icon={r.icon}
            />
          ))}
        </div>
        {rep === "custom" && (
          <Textarea
            className="mt-2"
            rows={2}
            maxLength={300}
            aria-label="Custom introduction"
            value={behavior.custom_intro ?? ""}
            onChange={(e) => onChange({ custom_intro: e.target.value })}
            placeholder={`e.g. Hi, this is ${name || "Maya"}, the virtual assistant for ${company}.`}
          />
        )}
        <p className="mt-2 text-xs text-zinc-500">Your agent never pretends to be human — if someone asks, it says it&apos;s an AI.</p>
      </div>

      <StepFineTune behavior={behavior} onChange={onChange} {...fineTune} />
    </div>
  );
}
