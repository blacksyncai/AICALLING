"use client";

import { Wrench } from "lucide-react";
import type { Call } from "@/lib/types";
import { cn, toolLabel } from "@/lib/utils";

export function fmtTs(ts?: number) {
  if (ts === undefined) return "";
  const s = Math.max(0, Math.round(ts));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** A call's conversation: agent on the left, contact on the right, tool steps as small lines. */
export function TranscriptLines({ transcript }: { transcript: NonNullable<Call["transcript"]> }) {
  return (
    <>
      {transcript.map((t, i) =>
        t.role === "tool" ? (
          toolLabel(t.tool, t.args) && (
            <div key={i} className="flex items-center gap-2 pl-1 text-[11px] text-zinc-500">
              <Wrench className="h-3 w-3" />
              <span className="truncate font-medium text-zinc-700">{toolLabel(t.tool, t.args)}</span>
              <span className="ml-auto shrink-0">{fmtTs(t.ts)}</span>
            </div>
          )
        ) : (
          <div key={i} className={cn("flex gap-3", t.role === "user" && "flex-row-reverse")}>
            <div
              className={cn(
                "max-w-[80%] rounded-2xl px-3.5 py-2 text-sm",
                t.role === "user" ? "rounded-tr-sm bg-brand-600 text-white" : "rounded-tl-sm bg-zinc-100 text-zinc-800",
              )}
            >
              {t.text}
            </div>
            <span className="self-end text-[10px] text-zinc-400">{fmtTs(t.ts)}</span>
          </div>
        ),
      )}
    </>
  );
}
