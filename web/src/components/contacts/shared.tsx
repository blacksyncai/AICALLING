"use client";

import { Badge } from "@/components/ui";
import { OUTCOME_TONE, cn, humanize } from "@/lib/utils";

export const CONTACT_STATUSES = [
  "new",
  "calling",
  "interested",
  "callback",
  "qualified",
  "meeting_booked",
  "not_interested",
  "not_qualified",
  "no_answer",
  "voicemail",
  "screened",
  "language_barrier",
  "hung_up",
  "completed",
  "failed",
] as const;

export type BulkAction = "delete" | "add_to_campaign" | "set_status" | "add_tag" | "dnc_on" | "dnc_off";

export interface ImportResult {
  created: number;
  skipped: number;
  duplicates: number;
}

const AVATAR_TONES = [
  "bg-orange-500 text-white",
  "bg-amber-500 text-white",
  "bg-zinc-800 text-white",
  "bg-rose-500 text-white",
  "bg-emerald-600 text-white",
  "bg-sky-600 text-white",
  "bg-violet-500 text-white",
];

export function initials(name: string) {
  const parts = (name || "").replace(/[^A-Za-z0-9 +]/g, " ").trim().split(/\s+/);
  if (!parts[0]) return "?";
  if (parts[0].startsWith("+")) return "#";
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function ContactAvatar({ name, size = "md" }: { name: string; size?: "md" | "lg" }) {
  const tone = AVATAR_TONES[[...(name || "?")].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_TONES.length];
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-semibold",
        size === "lg" ? "h-12 w-12 text-base" : "h-9 w-9 text-[11px]",
        tone,
      )}
    >
      {initials(name)}
    </span>
  );
}

export function statusTone(status: string) {
  if (status === "new") return "blue" as const;
  if (status === "calling") return "brand" as const;
  return OUTCOME_TONE[status] ?? "gray";
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{humanize(status)}</Badge>;
}

const PILL: Record<string, string> = {
  blue: "bg-blue-50 text-blue-700 ring-blue-600/10 [--dot:var(--color-blue-500)]",
  brand: "bg-brand-50 text-brand-700 ring-brand-600/10 [--dot:var(--color-brand-500)]",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/10 [--dot:var(--color-emerald-500)]",
  amber: "bg-amber-50 text-amber-700 ring-amber-600/10 [--dot:var(--color-amber-500)]",
  red: "bg-red-50 text-red-700 ring-red-600/10 [--dot:var(--color-red-500)]",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/10 [--dot:var(--color-violet-500)]",
  gray: "bg-zinc-100 text-zinc-600 ring-zinc-500/10 [--dot:var(--color-zinc-400)]",
};

/** Status as a soft pill with a coloured dot (the contacts table). */
export function StatusPill({ status, label }: { status: string; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset", PILL[statusTone(status)] ?? PILL.gray)}>
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--dot)]" />
      {label}
    </span>
  );
}

export function DncBadge({ className }: { className?: string }) {
  return (
    <Badge tone="red" className={cn("shrink-0", className)}>
      <span title="On the Do-Not-Call list — agents will never call this contact">DNC</span>
    </Badge>
  );
}

export function TagChip({ tag, onRemove }: { tag: string; onRemove?: () => void }) {
  return (
    <span className="inline-flex max-w-[140px] items-center gap-1 rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[11px] font-medium text-zinc-700">
      <span className="truncate">{tag}</span>
      {onRemove && (
        <button type="button" onClick={onRemove} className="-mr-0.5 rounded-full px-0.5 text-zinc-400 hover:text-zinc-800" aria-label={`Remove tag ${tag}`}>
          ×
        </button>
      )}
    </span>
  );
}

export const parseTags = (s: string) =>
  [...new Set(s.split(",").map((t) => t.trim()).filter(Boolean))];
