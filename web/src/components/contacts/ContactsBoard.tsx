"use client";

import { MotionConfig } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Spinner } from "@/components/ui";
import { Column, gentleSpring, type CardData, type ColumnData, type ColumnStatus, type DragState } from "@/components/ui/kanban-board";
import { api, post } from "@/lib/api";
import type { ContactList } from "@/lib/types";
import { outcomeLabel, timeAgo } from "@/lib/utils";

/* The pipeline as a board: one column per stage, drag a contact to change its status. */

const STAGES: { status: string; kind: ColumnStatus; color: string }[] = [
  { status: "new", kind: "todo", color: "#a1a1aa" },
  { status: "completed", kind: "todo", color: "#71717a" },
  { status: "interested", kind: "in-progress", color: "#2563eb" },
  { status: "callback", kind: "in-progress", color: "#d97706" },
  { status: "meeting_booked", kind: "in-progress", color: "#059669" },
  { status: "not_interested", kind: "todo", color: "#d4d4d8" },
];
const PER_COLUMN = 40;

const dot = (color: string) => (
  <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.4">
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="3.5" fill={color} stroke="none" />
  </svg>
);

export function ContactsBoard({ q, campaignId, counts, onChanged }: { q: string; campaignId: string; counts: Record<string, number>; onChanged: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const urls = useMemo(
    () =>
      STAGES.map((s) => {
        const p = new URLSearchParams({ status: s.status, page: "1", page_size: String(PER_COLUMN) });
        if (q) p.set("q", q);
        if (campaignId) p.set("campaign_id", campaignId);
        return `/api/contacts?${p}`;
      }),
    [q, campaignId],
  );
  const { data, mutate, isLoading } = useSWR(["contacts-board", ...urls], () => Promise.all(urls.map((u) => api<ContactList>(u))), { keepPreviousData: true });
  const [columns, setColumns] = useState<ColumnData[]>([]);
  const [moved, setMoved] = useState<Record<string, number>>({}); // count changes not yet reloaded
  const [dragState, setDragState] = useState<DragState>(null);

  useEffect(() => {
    if (!data) return;
    setMoved({});
    setColumns(
      STAGES.map((s, i) => ({
        id: s.status,
        title: outcomeLabel(s.status),
        status: s.kind,
        icon: dot(s.color),
        cards: data[i].items.map(
          (c): CardData => ({
            id: c.id,
            title: c.name || c.phone,
            subtitle: [c.company, c.role].filter(Boolean).join(" · ") || c.phone,
            tags: [
              ...(c.do_not_call ? [{ label: "DNC", variant: "bug" as const }] : []),
              ...c.tags.slice(0, 2).map((t) => ({ label: t, variant: "feature" as const })),
            ],
            assignee: { name: c.name || "#" },
            date: c.last_called_at ? timeAgo(c.last_called_at) : "Not called",
          }),
        ),
      })),
    );
  }, [data]);

  async function onDrop(cardId: string, from: string, to: string) {
    if (from === to) return;
    const before = columns;
    const card = columns.find((c) => c.id === from)?.cards.find((c) => c.id === cardId);
    if (!card) return;
    setColumns((prev) =>
      prev.map((col) => (col.id === from ? { ...col, cards: col.cards.filter((c) => c.id !== cardId) } : col.id === to ? { ...col, cards: [card, ...col.cards] } : col)),
    );
    setMoved((m) => ({ ...m, [from]: (m[from] ?? 0) - 1, [to]: (m[to] ?? 0) + 1 }));
    try {
      await post("/api/contacts/bulk", { ids: [cardId], action: "set_status", status: to });
      toast(`${card.title} moved to ${outcomeLabel(to)}`);
      onChanged();
    } catch (e) {
      setColumns(before);
      setMoved({});
      toast((e as Error).message, "error");
      mutate();
    }
  }

  if (!data && isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <MotionConfig transition={gentleSpring}>
      <div
        className="overflow-x-auto px-4 pb-5 pt-4 sm:px-5"
        style={{
          ["--muted" as string]: "#ffffff",
          ["--border" as string]: "rgba(24,24,27,.08)",
          ["--foreground" as string]: "#18181b",
          ["--muted-foreground" as string]: "#71717a",
        }}
      >
        <div className="grid min-w-[1180px] auto-cols-fr grid-flow-col gap-4">
          {columns.map((col) => {
            const total = (counts[col.id] ?? 0) + (moved[col.id] ?? 0);
            return (
              <div key={col.id} className="flex h-[calc(100vh-360px)] min-h-[420px] flex-col rounded-2xl bg-zinc-50/80 p-3 ring-1 ring-zinc-100">
                <Column
                  column={{ ...col, count: Math.max(total, col.cards.length) }}
                  dragState={dragState}
                  onCardClick={(c) => router.push(`/contacts/${c.id}`)}
                  onDrop={onDrop}
                  setDragState={setDragState}
                />
                {total > col.cards.length && <div className="pt-2 text-center text-[11px] text-zinc-400">Showing {col.cards.length} of {total.toLocaleString()}</div>}
              </div>
            );
          })}
        </div>
      </div>
    </MotionConfig>
  );
}
