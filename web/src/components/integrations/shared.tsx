"use client";

import { Check, Copy } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button, Modal } from "@/components/ui";
import { useToast } from "@/components/toast";
import { cn } from "@/lib/utils";
import type { WebhookEvent } from "@/lib/types";

export const EVENT_LABEL: Record<WebhookEvent, string> = {
  "call.completed": "Call finished",
  "meeting.booked": "Meeting booked",
  "contact.created": "New contact",
};

export const EVENT_INFO: Record<WebhookEvent, string> = {
  "call.completed": "Every finished call, with the outcome, summary and details the agent collected",
  "meeting.booked": "When an agent books a meeting, with the time and the contact's details",
  "contact.created": "When a contact is added, from a list import, a form or another app",
};

export const ALL_EVENTS = Object.keys(EVENT_INFO) as WebhookEvent[];

async function writeClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for non-secure contexts (http on a LAN IP).
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  }
}

export function CopyButton({ text, label = "Copy", className, dark }: { text: string; label?: string; className?: string; dark?: boolean }) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();
  return (
    <button
      type="button"
      onClick={async () => {
        if (await writeClipboard(text)) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } else toast("Couldn't copy — select the text and copy it manually.", "error");
      }}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium transition-colors",
        dark ? "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100" : "border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50",
        className,
      )}
      aria-label={label}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "Copied" : label}
    </button>
  );
}

export function CodeBlock({ code, title }: { code: string; title?: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg bg-zinc-950">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-800 py-1 pl-3 pr-1">
        <span className="truncate text-[11px] font-medium text-zinc-400">{title ?? ""}</span>
        <CopyButton text={code} dark />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-zinc-100">
        <code>{code}</code>
      </pre>
    </div>
  );
}

/** Compact on/off switch for list rows (the ui Toggle is a full-width settings row). */
export function Switch({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
        checked ? "bg-brand-600" : "bg-zinc-300",
      )}
    >
      <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

export function ConfirmModal({
  open,
  onClose,
  title,
  body,
  confirmLabel,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="text-sm text-zinc-600">{body}</div>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="danger"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
            } finally {
              setBusy(false);
            }
          }}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
