"use client";

import { forwardRef, useCallback, useLayoutEffect, useMemo, useRef, useState, type ComponentProps } from "react";
import { X } from "lucide-react";
import { Select } from "@/components/ui";
import { cn } from "@/lib/utils";
import { addExpression, editExpressionText, expressionRanges, EXPRESSION_CHOICES, parseExpressions, removeExpression } from "@/lib/prompt-expressions";

type Props = Omit<ComponentProps<"textarea">, "value" | "onChange"> & {
  value: string;
  onTextChange: (value: string) => void;
  supported: boolean;
  enabled?: boolean;
  onExpressionAdded?: () => void;
  autoGrow?: boolean;
};

export const ExpressionTextarea = forwardRef<HTMLTextAreaElement, Props>(function ExpressionTextarea(
  { value, onTextChange, supported, enabled = false, onExpressionAdded, autoGrow, className, onSelect, onScroll, ...rest }, forwardedRef,
) {
  const textarea = useRef<HTMLTextAreaElement | null>(null);
  const overlay = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLPreElement>(null);
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const { text } = useMemo(() => parseExpressions(value), [value]);
  const ranges = useMemo(() => expressionRanges(value), [value]);
  const setRef = useCallback((element: HTMLTextAreaElement | null) => {
    textarea.current = element;
    if (typeof forwardedRef === "function") forwardedRef(element);
    else if (forwardedRef) forwardedRef.current = element;
  }, [forwardedRef]);
  useLayoutEffect(() => {
    const input = textarea.current;
    if (!input) return;
    const sync = () => {
      if (content.current) content.current.style.width = `${input.clientWidth}px`;
      if (overlay.current) { overlay.current.scrollTop = input.scrollTop; overlay.current.scrollLeft = input.scrollLeft; }
    };
    if (autoGrow) { input.style.height = "auto"; input.style.height = `${input.scrollHeight + 2}px`; }
    sync();
    const resize = new ResizeObserver(sync); resize.observe(input);
    return () => resize.disconnect();
  }, [text, autoGrow]);

  const selected = selection.end > selection.start && selection.end <= text.length;
  const pieces = [];
  let cursor = 0;
  for (const range of ranges.filter((r) => r.kind === "emotion")) {
    if (range.start > cursor) pieces.push(text.slice(cursor, range.start));
    pieces.push(<mark key={range.marker} className={supported && enabled ? "rounded-sm bg-orange-100 text-zinc-900!" : "rounded-sm bg-zinc-100 text-zinc-900!"}>{text.slice(range.start, range.end)}</mark>);
    cursor = range.end;
  }
  pieces.push(text.slice(cursor));
  const focusRange = (start: number, end: number) => {
    setSelection({ start, end });
    requestAnimationFrame(() => { textarea.current?.focus(); textarea.current?.setSelectionRange(start, end); });
  };
  return (
    <div className="min-w-0 space-y-2" data-slot="expression-editor">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-zinc-500">{supported ? "Highlight a spoken phrase to choose its delivery." : "Choose a compatible voice to add expressions."}</span>
        <Select aria-label="Add expression to selected text" className="max-w-full sm:max-w-60" value="" disabled={!supported || !selected}
          onChange={(event) => {
            const next = addExpression(value, selection.start, selection.end, event.target.value);
            onExpressionAdded?.();
            if (next !== value) onTextChange(next);
            focusRange(selection.start, selection.end);
          }}>
          <option value="">{selected ? "Add expression…" : "Highlight text first"}</option>
          {EXPRESSION_CHOICES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </Select>
      </div>
      <div className="relative rounded-lg bg-white">
        <div aria-hidden="true" ref={overlay} className="pointer-events-none absolute inset-px overflow-hidden rounded-lg">
          <pre ref={content} className="m-0 whitespace-pre-wrap break-words p-3 font-mono text-[13px] leading-6 text-zinc-900!">{pieces}{"\u200b"}</pre>
        </div>
        <textarea {...rest} ref={setRef} value={text} spellCheck={false}
          className={cn("relative block w-full resize-y rounded-lg border border-zinc-200 bg-transparent p-3 font-mono text-[13px] leading-6 text-transparent caret-zinc-900 shadow-xs selection:bg-brand-200/60 placeholder:text-zinc-400 focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-500/10", className)}
          onChange={(event) => { onTextChange(editExpressionText(value, event.target.value)); setSelection({ start: 0, end: 0 }); }}
          onSelect={(event) => { setSelection({ start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd }); onSelect?.(event); }}
          onScroll={(event) => { if (overlay.current) { overlay.current.scrollTop = event.currentTarget.scrollTop; overlay.current.scrollLeft = event.currentTarget.scrollLeft; } onScroll?.(event); }} />
      </div>
      {ranges.length > 0 && <div className="flex flex-wrap gap-1.5" aria-label="Expressions in this text">
        {ranges.map((range) => <span key={range.marker} className={cn("inline-flex max-w-full items-center rounded-full border text-xs", supported && enabled ? "border-orange-200 bg-orange-50 text-orange-900" : "border-zinc-200 bg-zinc-50 text-zinc-500")}>
          <button type="button" onClick={() => focusRange(range.start, range.end)} className="max-w-72 truncate px-2.5 py-1" title={text.slice(range.start, range.end)}>
            {range.label}{!enabled ? " (off)" : ""}{range.end > range.start ? ` · ${text.slice(range.start, range.end).trim()}` : ""}
          </button>
          <button type="button" aria-label={`Remove ${range.label} expression`} onClick={() => { onTextChange(removeExpression(value, range.marker)); setSelection({ start: 0, end: 0 }); }} className="mr-1 rounded-full p-1 hover:bg-orange-100"><X aria-hidden className="size-3" /></button>
        </span>)}
      </div>}
    </div>
  );
});
