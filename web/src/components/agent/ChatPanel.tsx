"use client";

import { RotateCcw, Send, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import type { ChatTurn, ToolEvent } from "@/lib/types";
import { cn, humanize, toolLabel, outcomeLabel } from "@/lib/utils";
import { Button, Notice } from "../ui";
import { AiOrb } from "../ui/ai-orb";

type Item = ChatTurn | { role: "tool"; event: ToolEvent };

function renderVars(text: string, vars: Record<string, string>) {
  return text.replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (_, k) => vars[k] || (k === "name" ? "there" : k === "company" ? "your company" : ""));
}

export function ChatPanel({
  agentId,
  firstMessage,
  enabled,
  variables,
  beforeStart,
}: {
  agentId: string;
  firstMessage: string;
  enabled: boolean;
  variables: Record<string, string>;
  beforeStart: () => Promise<boolean>;
}) {
  const opener = (): Item[] => (firstMessage.trim() ? [{ role: "assistant", content: renderVars(firstMessage, variables) }] : []);
  const [items, setItems] = useState<Item[]>(opener);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ended, setEnded] = useState<string | null>(null);
  const [state, setState] = useState<Record<string, unknown>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [items, busy]);

  function reset() {
    setItems(opener());
    setEnded(null);
    setError("");
    setState({});
  }

  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    if (!(await beforeStart())) return;
    const next: Item[] = [...items, { role: "user", content: text }];
    setItems(next);
    setInput("");
    setBusy(true);
    setError("");
    try {
      const history = next.filter((i): i is ChatTurn => i.role !== "tool");
      const res = await post<{ reply: string; tool_events: ToolEvent[]; ended: boolean; outcome: string | null; state: Record<string, unknown> }>(
        `/api/agents/${agentId}/chat`,
        { messages: history, variables, state },
      );
      setState(res.state ?? {});
      setItems((cur) => [
        ...cur,
        ...res.tool_events.map((event) => ({ role: "tool" as const, event })),
        ...(res.reply ? [{ role: "assistant" as const, content: res.reply }] : []),
      ]);
      if (res.ended) setEnded(res.outcome ?? "completed");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs text-zinc-500">Type as the person being called. Same prompt, knowledge and tools as the voice agent.</p>
        <button onClick={reset} className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100" title="Restart conversation">
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>
      <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto rounded-lg bg-zinc-50 p-3">
        {items.map((m, i) =>
          m.role === "tool" ? (
            toolLabel(m.event.tool, m.event.args) && (
              <div key={i} className="flex items-start gap-1.5 text-[11px] text-zinc-500">
                <Wrench className="mt-0.5 h-3 w-3 shrink-0" />
                <span>
                  <span className="font-medium text-zinc-700">{toolLabel(m.event.tool, m.event.args)}</span>
                  {m.event.result ? ` — ${m.event.result}` : ""}
                </span>
              </div>
            )
          ) : (
            <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              <div
                className={cn(
                  "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm",
                  m.role === "user" ? "rounded-br-sm bg-brand-600 text-white" : "rounded-bl-sm border border-zinc-200 bg-white text-zinc-800",
                )}
              >
                {m.content}
              </div>
            </div>
          ),
        )}
        {busy && (
          <div className="flex items-center gap-2 px-2 py-1" role="status">
            <AiOrb size="sm" state="thinking" decorative />
            <span className="text-xs text-zinc-500">Preparing a reply…</span>
          </div>
        )}
        {ended && (
          <div className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-center text-xs text-zinc-600">
            Agent ended the call · outcome <span className="font-medium">{outcomeLabel(ended)}</span>
          </div>
        )}
      </div>
      {error && (
        <div className="mt-2">
          <Notice tone="red">{error}</Notice>
        </div>
      )}
      {!enabled && (
        <div className="mt-2">
          <Notice>
            Chat testing isn&apos;t available right now. Message us in the chat and we&apos;ll get it sorted.
          </Notice>
        </div>
      )}
      <form onSubmit={send} className="mt-3 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={ended ? "Call ended — reset to try again" : "Reply as the contact…"}
          disabled={!enabled || !!ended}
          className="h-9 flex-1 rounded-lg border border-zinc-200 px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:bg-zinc-50"
        />
        <Button variant="primary" disabled={!enabled || !input.trim() || !!ended} loading={busy} aria-label="Send">
          {!busy && <Send className="h-4 w-4" />}
        </Button>
      </form>
    </div>
  );
}
