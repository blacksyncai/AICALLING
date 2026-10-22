"use client";

import { CheckCircle2, ChevronDown, FlaskConical, XCircle } from "lucide-react";
import { useState } from "react";
import { post } from "@/lib/api";
import { cn, humanize, outcomeLabel } from "@/lib/utils";
import { Button, Notice } from "../ui";
import { AiOrb } from "../ui/ai-orb";

interface Check {
  check: string;
  result: "pass" | "fail" | "n/a";
  evidence?: string;
}
interface Turn {
  role: "assistant" | "user" | "tool";
  content?: string;
  tool?: string;
  result?: string;
}
interface Result {
  id: string;
  title: string;
  passed: boolean;
  outcome: string | null;
  checks: Check[];
  problems: string[];
  transcript: Turn[];
  error?: string;
}

/** Simulated callers put the agent through tricky situations in text; each conversation is graded. */
export function StressTest({ agentId, variables, beforeStart }: { agentId: string; variables: Record<string, string>; beforeStart: () => Promise<boolean> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<{ results: Result[]; passed: number; total: number } | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  async function run() {
    if (!(await beforeStart())) return;
    setBusy(true);
    setError("");
    setData(null);
    try {
      setData(await post(`/api/agents/${agentId}/stress-test`, { variables }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs text-zinc-500">
          Simulated callers try the situations that trip agents up: asking for times again, &ldquo;who is this?&rdquo;, objections, opt-outs and more. Takes about a minute.
        </p>
        <Button size="sm" variant="primary" loading={busy} onClick={() => void run()}>
          {!busy && <FlaskConical className="h-3.5 w-3.5" />} {data ? "Run again" : "Run stress test"}
        </Button>
      </div>
      {error && <Notice tone="red">{error}</Notice>}
      <div className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto">
        {busy && (
          <div className="flex items-center gap-2 rounded-lg bg-zinc-50 px-3 py-3" role="status">
            <AiOrb size="sm" state="thinking" decorative />
            <span className="text-xs text-zinc-500">Running test calls…</span>
          </div>
        )}
        {data && (
          <div className="rounded-lg bg-zinc-50 px-3 py-2 text-sm font-medium text-zinc-800">
            {data.passed} of {data.total} passed
          </div>
        )}
        {data?.results.map((r) => (
          <div key={r.id} className="rounded-lg border border-zinc-200 bg-white">
            <button type="button" onClick={() => setOpen(open === r.id ? null : r.id)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
              {r.passed ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" /> : <XCircle className="h-4 w-4 shrink-0 text-red-500" />}
              <span className="flex-1 text-sm text-zinc-800">{r.title}</span>
              <ChevronDown className={cn("h-4 w-4 text-zinc-400 transition-transform", open === r.id && "rotate-180")} />
            </button>
            {(!r.passed || open === r.id) && (
              <div className="space-y-1 border-t border-zinc-100 px-3 py-2 text-xs">
                {r.error && <p className="text-red-600">{r.error}</p>}
                {r.checks.filter((c) => open === r.id || c.result === "fail").map((c, i) => (
                  <p key={i} className={c.result === "fail" ? "text-red-700" : c.result === "pass" ? "text-zinc-600" : "text-zinc-400"}>
                    {c.result === "fail" ? "✗" : c.result === "pass" ? "✓" : "–"} {c.check}
                    {c.result === "fail" && c.evidence ? <span className="text-zinc-500"> — &ldquo;{c.evidence}&rdquo;</span> : null}
                  </p>
                ))}
                {r.problems.map((p, i) => <p key={`p${i}`} className="text-amber-700">⚠ {p}</p>)}
              </div>
            )}
            {open === r.id && (
              <div className="space-y-1.5 border-t border-zinc-100 bg-zinc-50 px-3 py-2">
                {r.transcript.map((t, i) =>
                  t.role === "tool" ? (
                    <p key={i} className="text-[11px] text-zinc-500">🔧 {t.tool}{t.result ? ` — ${t.result}` : ""}</p>
                  ) : (
                    <p key={i} className="text-xs"><span className="font-medium text-zinc-700">{t.role === "assistant" ? "Agent" : "Caller"}:</span> {t.content}</p>
                  ),
                )}
                {r.outcome && <p className="text-[11px] text-zinc-500">Ended · {outcomeLabel(r.outcome)}</p>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
