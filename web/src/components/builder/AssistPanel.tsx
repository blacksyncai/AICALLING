"use client";

import { ArrowRight, Check, Pencil, RefreshCw, SendHorizontal, Sparkles } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui";
import type { AssistItem, AssistResponse, DraftGoal } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { Chip } from "./parts";
import { goalBasis, type GoalUpdater } from "./goal";
import { VoiceInput } from "@/components/MicButton";

/** Keep onboarding short: at most this many assist rounds per goal (the server caps questions too). */
const MAX_ROUNDS = 2;
export const YOU_DECIDE = "You decide";

const resolved = (i: AssistItem) => !!i.answer || i.skipped || !!i.delegated;

export function AssistPanel({
  goal,
  setGoal,
  canAsk,
  runAssist,
}: {
  goal: DraftGoal;
  setGoal: GoalUpdater;
  canAsk: boolean;
  runAssist: (goal: DraftGoal) => Promise<AssistResponse>;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const busy = useRef(false);

  const items = goal.assistant ?? [];
  const done = items.filter(resolved);
  const pending = items.filter((i) => !resolved(i));
  const rounds = goal.assist_rounds ?? 0;
  const basis = goalBasis(goal);
  const started = !!goal.understanding;
  const stale = started && goal.assist_basis !== undefined && goal.assist_basis !== basis;

  async function ask() {
    if (busy.current || !canAsk) return;
    busy.current = true;
    setLoading(true);
    setError("");
    setEditing(null);
    const sentBasis = basis;
    const changed = goal.assist_basis !== undefined && goal.assist_basis !== sentBasis;
    // Unanswered questions are dropped before asking again; answers are kept (the AI flags ones that no longer apply).
    const sent: DraftGoal = { ...goal, assistant: (goal.assistant ?? []).filter(resolved), assist_rounds: changed ? 0 : rounds };
    try {
      const res = await runAssist(sent);
      setGoal((g) => {
        const kept = (g.assistant ?? []).filter((i) => resolved(i) && !res.irrelevant.includes(i.id));
        const taken = new Set(kept.map((i) => i.id));
        const fresh: AssistItem[] = res.questions.map((q) => {
          let id = q.id;
          for (let n = 2; taken.has(id); n++) id = `${q.id}_${n}`;
          taken.add(id);
          return { id, question: q.question, suggestions: q.suggestions, reason: q.reason, answer: null, skipped: false };
        });
        return {
          ...g,
          assistant: [...kept, ...fresh],
          understanding: res.understanding,
          recommendation: res.recommendation,
          ready: res.ready,
          assist_rounds: (sent.assist_rounds ?? 0) + 1,
          assist_basis: sentBasis,
        };
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }

  // Answered everything from this round but the AI still needs a bit more → one more short round.
  const askRef = useRef(ask);
  useEffect(() => {
    askRef.current = ask;
  });
  const autoNext = started && !stale && !loading && !error && !goal.ready && pending.length === 0 && done.length > 0 && rounds < MAX_ROUNDS;
  useEffect(() => {
    if (autoNext) void askRef.current();
  }, [autoNext]);

  function answer(id: string, patch: Partial<AssistItem>) {
    setGoal((g) => ({
      ...g,
      assistant: (g.assistant ?? []).map((i) => (i.id === id ? { ...i, answer: null, skipped: false, delegated: false, ...patch } : i)),
    }));
    setEditing(null);
  }

  const current = editing ? items.find((i) => i.id === editing) : pending[0];

  return (
    <section aria-label="AI assistant" aria-live="polite" className="space-y-3 rounded-xl border border-zinc-200 bg-zinc-50/60 p-3 sm:p-4">
      {!started && !loading && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-center gap-2 text-xs text-zinc-500">
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-brand-600" />
            {canAsk ? "AI checks your mission and asks only about details that would change the script." : "Describe the mission, and AI will check whether anything important is missing."}
          </p>
          <Button size="sm" variant="primary" onClick={ask} disabled={!canAsk} className="shrink-0">
            Quick check <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {started && (
        <Bubble>
          {goal.understanding}
          {stale && !loading && (
            <span className="mt-2 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
              You changed the goal.
              <button type="button" onClick={ask} disabled={!canAsk} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline disabled:opacity-50">
                <RefreshCw className="h-3 w-3" /> Update
              </button>
            </span>
          )}
        </Bubble>
      )}

      {done.length > 0 && (
        <ul className="space-y-1.5">
          {done.map((i) =>
            editing === i.id ? null : (
              <li key={i.id}>
                <button
                  type="button"
                  onClick={() => setEditing(i.id)}
                  className="group flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-white focus-visible:outline-2 focus-visible:outline-brand-500"
                  aria-label={`Edit answer: ${i.question}`}
                >
                  <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-600" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs text-zinc-500">{i.question}</span>
                    <span className={cn("block text-sm", i.skipped ? "text-zinc-400 italic" : "text-zinc-900")}>
                      {i.delegated ? "AI will decide" : i.skipped ? "Skipped" : i.answer}
                    </span>
                  </span>
                  <Pencil className="mt-1 h-3 w-3 shrink-0 text-zinc-300 group-hover:text-zinc-500" />
                </button>
              </li>
            ),
          )}
        </ul>
      )}

      {current && !loading && (
        <QuestionCard
          key={current.id}
          item={current}
          progress={!editing && pending.length > 1 ? `1 of ${pending.length}` : undefined}
          onAnswer={(text) => answer(current.id, { answer: text })}
          onDecide={() => answer(current.id, { answer: YOU_DECIDE, delegated: true })}
          onSkip={() => answer(current.id, { skipped: true })}
          onCancel={editing ? () => setEditing(null) : undefined}
        />
      )}

      {loading && (
        <Bubble>
          <span className="inline-flex items-center gap-1" aria-label="Thinking">
            <Dot delay="0ms" />
            <Dot delay="150ms" />
            <Dot delay="300ms" />
          </span>
        </Bubble>
      )}

      {started && !loading && !stale && pending.length === 0 && (goal.ready || rounds >= MAX_ROUNDS) && (
        <Bubble>
          That&apos;s all I need — you can generate your agent now.
          {goal.recommendation && <span className="mt-1 block text-xs text-zinc-500">Tip: {goal.recommendation}</span>}
        </Bubble>
      )}

      {error && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-red-700" role="alert">
          {error}
          <button type="button" onClick={ask} className="font-medium underline">
            Try again
          </button>
        </p>
      )}
    </section>
  );
}

function Bubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 transition duration-300 starting:translate-y-1 starting:opacity-0">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full brand-gradient text-white">
        <Sparkles className="h-3 w-3" />
      </span>
      <div className="min-w-0 rounded-2xl rounded-tl-sm bg-white px-3 py-2 text-sm leading-relaxed text-zinc-800 shadow-xs ring-1 ring-zinc-200">{children}</div>
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400" style={{ animationDelay: delay }} />;
}

function QuestionCard({
  item,
  progress,
  onAnswer,
  onDecide,
  onSkip,
  onCancel,
}: {
  item: AssistItem;
  progress?: string;
  onAnswer: (text: string) => void;
  onDecide: () => void;
  onSkip: () => void;
  onCancel?: () => void;
}) {
  const id = useId();
  const suggestions = item.suggestions ?? [];
  const typed = item.answer && !item.delegated && !suggestions.includes(item.answer) ? item.answer : "";
  const [text, setText] = useState(typed);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (text.trim()) onAnswer(text.trim());
  }

  return (
    <div className="ml-8 rounded-xl border border-zinc-200 bg-white p-3 transition duration-300 starting:translate-y-1 starting:opacity-0">
      <div className="flex items-start justify-between gap-2">
        <p id={`${id}-q`} className="text-sm font-medium text-zinc-900">
          {item.question}
        </p>
        {progress && <span className="shrink-0 text-[11px] text-zinc-400">{progress}</span>}
      </div>
      {item.reason && <p className="mt-0.5 text-xs text-zinc-500">{item.reason}</p>}
      {suggestions.length > 0 && (
        <div role="group" aria-labelledby={`${id}-q`} className="mt-2.5 flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <Chip key={s} onClick={() => onAnswer(s)} className={cn(item.answer === s && "border-brand-500 bg-brand-50 text-brand-800")}>
              {s}
            </Chip>
          ))}
        </div>
      )}
      <form onSubmit={submit} className="mt-2.5 flex gap-2">
        <VoiceInput value={text} onValue={setText} placeholder="Type or say your own answer" aria-label={`Your answer: ${item.question}`} className="h-8 text-sm" />
        <Button size="sm" type="submit" disabled={!text.trim()} aria-label="Send answer">
          <SendHorizontal className="h-3.5 w-3.5" />
        </Button>
      </form>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <button type="button" onClick={onDecide} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
          <Sparkles className="h-3 w-3" /> You decide
        </button>
        <button type="button" onClick={onSkip} className="font-medium text-zinc-500 hover:text-zinc-800">
          Skip
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className="ml-auto font-medium text-zinc-500 hover:text-zinc-800">
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
