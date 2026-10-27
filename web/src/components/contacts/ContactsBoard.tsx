"use client";

import { Kanban } from "lucide-react";
import styles from "./contacts-board.module.css";
import { MotionConfig } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Spinner } from "@/components/ui";
import { Column, gentleSpring, type CardData, type ColumnData, type ColumnStatus, type DragState } from "@/components/ui/kanban-board";
import { api, post } from "@/lib/api";
import type { ContactList } from "@/lib/types";
import { formatDuration, outcomeLabel, timeAgo } from "@/lib/utils";

/* The pipeline as a board: one column per stage, drag a contact to change its status. */

// Every contact status has a home. A column's first status is what a card dropped into it becomes.
const STAGES: { status: string; title: string; includes: string[]; kind: ColumnStatus; color: string }[] = [
  { status: "new", title: "New", includes: ["new", "calling"], kind: "todo", color: "#a1a1aa" },
  { status: "no_answer", title: "No answer yet", includes: ["no_answer", "voicemail", "screened", "failed"], kind: "todo", color: "#94a3b8" },
  { status: "completed", title: "Talked, no decision", includes: ["completed", "hung_up", "language_barrier"], kind: "todo", color: "#71717a" },
  { status: "interested", title: "Interested", includes: ["interested", "qualified"], kind: "in-progress", color: "#2563eb" },
  { status: "callback", title: "Follow-up", includes: ["callback"], kind: "in-progress", color: "#d97706" },
  { status: "meeting_booked", title: "Meeting booked", includes: ["meeting_booked", "transferred"], kind: "in-progress", color: "#059669" },
  { status: "not_interested", title: "Not interested", includes: ["not_interested", "not_qualified", "wrong_number", "do_not_call"], kind: "todo", color: "#d4d4d8" },
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
        // Longest conversation first, so the best talks sit at the top of each stage.
        const p = new URLSearchParams({ status: s.includes.join(","), page: "1", page_size: String(PER_COLUMN), sort: "longest_call" });
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
        title: s.title,
        status: s.kind,
        icon: dot(s.color),
        cards: data[i].items.map(
          (c): CardData => ({
            id: c.id,
            title: c.name || c.phone,
            subtitle: [c.company, c.role].filter(Boolean).join(" · ") || c.phone,
            tags: [
              ...(c.do_not_call ? [{ label: "DNC", variant: "bug" as const }] : []),
              // Grouped columns: say which one it is ("Qualified", "Voicemail", "Wrong number").
              ...(c.status !== s.status ? [{ label: outcomeLabel(c.status), variant: "design" as const }] : []),
              ...c.tags.slice(0, 2).map((t) => ({ label: t, variant: "feature" as const })),
            ],
            assignee: { name: c.name || "#" },
            date: c.longest_call_seconds
              ? `${formatDuration(c.longest_call_seconds)} talk · ${timeAgo(c.last_called_at)}`
              : c.last_called_at ? timeAgo(c.last_called_at) : "Not called",
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
      toast(`${card.title} moved to ${STAGES.find((s) => s.status === to)?.title ?? outcomeLabel(to)}`);
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
        className={styles.board}
        aria-label="Contact pipeline board"
      >
        <div className={styles.header}>
          <div className={styles.heading}><span className={styles.boardIcon}><Kanban size={17} aria-hidden="true" /></span><div><h2>Contact board</h2><p>Your conversations, one stage at a time.</p></div></div>
          <span className={styles.hint}>Drag a card to move stages</span>
        </div>
        <div className={styles.scroller} tabIndex={0} aria-label="Pipeline stages, scroll horizontally">
        <div className={styles.columns}>
          {columns.map((col) => {
            const stage = STAGES.find((s) => s.status === col.id);
            const total = (stage?.includes ?? [col.id]).reduce((n, st) => n + (counts[st] ?? 0), 0) + (moved[col.id] ?? 0);
            return (
              <div key={col.id} className={styles.column} style={{ ["--stage-color" as string]: STAGES.find((s) => s.status === col.id)?.color }}>
                <Column
                  column={{ ...col, count: Math.max(total, col.cards.length) }}
                  dragState={dragState}
                  onCardClick={(c) => router.push(`/contacts/${c.id}`)}
                  onDrop={onDrop}
                  setDragState={setDragState}
                />
                {total > col.cards.length && <div className={styles.more}>Showing {col.cards.length} of {total.toLocaleString()}</div>}
              </div>
            );
          })}
        </div>
        </div>
      </div>
    </MotionConfig>
  );
}
