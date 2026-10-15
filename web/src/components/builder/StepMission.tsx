"use client";

import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { VoiceTextarea } from "@/components/MicButton";
import { Field, Input, Notice, Toggle } from "@/components/ui";
import { post } from "@/lib/api";
import { SOMETHING_ELSE, type AssistResponse, type BuilderCatalog, type DraftGoal, type MissionAdvanced } from "@/lib/builder";
import { AssistPanel } from "./AssistPanel";
import { MIN_DESCRIPTION } from "./goal";
import { Collapsible, StepTitle } from "./parts";
import { bookingStatus, type Behavior } from "./StepPersonality";

const ADVANCED: { key: keyof MissionAdvanced; label: string; placeholder: string }[] = [
  { key: "audience", label: "Who it talks to", placeholder: "e.g. Homeowners whose listing expired in the last 90 days" },
  { key: "qualification", label: "What makes a good lead", placeholder: "e.g. Still wants to sell within 6 months" },
  { key: "questions", label: "Questions it must ask", placeholder: "e.g. Timeline, price expectations, why it didn't sell" },
  { key: "objections", label: "Objections to expect", placeholder: "e.g. \"I'm going to wait\", \"I already have an agent\"" },
  { key: "booking", label: "When to book", placeholder: "e.g. Book a listing appointment when they're open to a call" },
  { key: "follow_up", label: "Follow-up", placeholder: "e.g. Offer a callback if now isn't a good time" },
  { key: "tone", label: "Tone", placeholder: "e.g. Friendly and low-pressure" },
];

export function missionReady(goal: DraftGoal): boolean {
  return (goal.mission ?? "").trim().length >= MIN_DESCRIPTION;
}

/** Step 3 — What should your agent accomplish? An AI-suggested mission the customer accepts or rewrites. */
export function StepMission({
  draftId,
  goal,
  setGoal,
  behavior,
  onBehavior,
  catalog,
  flush,
  runAssist,
  showErrors,
}: {
  draftId: string;
  goal: DraftGoal;
  setGoal: (fn: (g: DraftGoal) => DraftGoal) => void;
  behavior: Behavior;
  onBehavior: (p: Partial<Behavior>) => void;
  catalog: BuilderCatalog | undefined;
  /** Saves the draft so the suggestion is based on the latest answers. */
  flush: () => Promise<void>;
  /** Saves the draft, then asks the AI which missing details would change the script. */
  runAssist: (goal: DraftGoal) => Promise<AssistResponse>;
  showErrors: boolean;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const asked = useRef(false);
  const mission = goal.mission ?? "";
  const adv = goal.advanced ?? {};
  const calendar = bookingStatus(catalog) === "available";
  const transferOn = behavior.transfer_number !== undefined;

  async function suggest() {
    setLoading(true);
    setError("");
    try {
      await flush();
      const res = await post<{ mission: string; source: "ai" | "template" }>(`/api/agent-builder/drafts/${draftId}/mission`, {});
      if (res.mission) setGoal((g) => ({ ...g, mission: res.mission, mission_source: res.source }));
      else setError("We couldn't suggest a mission for this one. Describe it in your own words below.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  // Suggest one automatically the first time the step opens without a mission.
  useEffect(() => {
    if (asked.current || mission.trim()) return;
    asked.current = true;
    void suggest();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setAdv = (k: keyof MissionAdvanced, v: string) => setGoal((g) => ({ ...g, advanced: { ...g.advanced, [k]: v } }));
  const filled = ADVANCED.filter((a) => adv[a.key]?.trim()).length + (behavior.booking ? 1 : 0) + (transferOn ? 1 : 0);
  const fromAi = goal.mission_source === "ai" || goal.mission_source === "template";
  const label = goal.specialty?.key === SOMETHING_ELSE ? "your agent" : goal.specialty?.label;

  return (
    <div>
      <StepTitle title="What should your agent accomplish?" description="Tell us what a successful conversation looks like. We drafted one from your choices — keep it, edit it, or write your own." />

      <div className="space-y-5">
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-xs font-medium text-zinc-700">
              Mission
              {fromAi && !loading && (
                <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-medium text-brand-700">
                  <Sparkles className="h-3 w-3" /> Suggested{label ? ` for ${label}` : ""}
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => void suggest()}
              disabled={loading}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              {mission.trim() ? "Suggest another" : "Suggest one"}
            </button>
          </div>
          {loading && !mission.trim() ? (
            <div className="flex h-[104px] items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-200 bg-zinc-50 text-xs text-zinc-500" role="status">
              <Loader2 className="h-4 w-4 animate-spin text-brand-600" /> Drafting a mission from your answers…
            </div>
          ) : (
            <VoiceTextarea
              rows={4}
              value={mission}
              onValue={(v) => setGoal((g) => ({ ...g, mission: v, mission_source: "user" }))}
              placeholder="e.g. Reach out to homeowners with expired listings, learn whether they still want to sell and their timeline, and book a listing appointment with my team."
              aria-label="Mission"
              aria-invalid={showErrors && !missionReady(goal)}
            />
          )}
          {error && <p className="mt-1 text-xs text-amber-700">{error}</p>}
          {showErrors && !missionReady(goal) && <span className="mt-1 block text-xs text-red-600">Describe what a successful call looks like in a sentence or two.</span>}
        </div>

        <Field label="Anything else it should know? (optional)">
          <VoiceTextarea
            rows={2}
            value={goal.additional ?? ""}
            onValue={(v) => setGoal((g) => ({ ...g, additional: v }))}
            placeholder="e.g. Never discuss commission. Mention we've sold 200+ homes in Austin."
          />
        </Field>

        <AssistPanel goal={goal} setGoal={setGoal} canAsk={missionReady(goal) && !loading} runAssist={runAssist} />

        <Collapsible title="Advanced details" meta={filled ? `${filled} set` : "Optional"}>
          <div className="space-y-4">
            <p className="text-xs text-zinc-500">Leave any of these blank and your agent will use sensible defaults for its specialty.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {ADVANCED.map((a) => (
                <Field key={a.key} label={a.label}>
                  <Input value={adv[a.key] ?? ""} onChange={(e) => setAdv(a.key, e.target.value)} placeholder={a.placeholder} maxLength={300} />
                </Field>
              ))}
            </div>

            <Toggle
              checked={!!behavior.booking}
              onChange={(v) => onBehavior({ booking: v, decide_later: false })}
              label="Book appointments on the call"
              description={calendar ? "Uses your connected calendar." : "Your calendar isn't connected yet — the agent will offer times once you connect it in Integrations."}
            />
            <Toggle
              checked={transferOn}
              onChange={(v) =>
                onBehavior(v ? { transfer_number: "", decide_later: false } : { transfer_number: undefined, transfer_when: undefined })
              }
              label="Transfer interested callers to a person"
              description="Only when you add a number your team answers."
            />
            {transferOn && (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Transfer to">
                  <Input
                    type="tel"
                    value={behavior.transfer_number ?? ""}
                    onChange={(e) => onBehavior({ transfer_number: e.target.value })}
                    placeholder="+1 512 555 0100"
                    aria-invalid={showErrors && !behavior.transfer_number?.trim()}
                  />
                  {showErrors && !behavior.transfer_number?.trim() && <span className="mt-1 block text-xs text-red-600">Add the number, or turn transfers off.</span>}
                </Field>
                <Field label="When">
                  <Input value={behavior.transfer_when ?? ""} onChange={(e) => onBehavior({ transfer_when: e.target.value })} placeholder="e.g. They want to talk to an agent today" />
                </Field>
              </div>
            )}
            {!calendar && behavior.booking && (
              <Notice tone="amber">Booking stays off on calls until a calendar is connected. Everything else works now.</Notice>
            )}
          </div>
        </Collapsible>
      </div>
    </div>
  );
}
