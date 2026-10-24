"use client";

import { Column, gentleSpring, type ColumnData, type DragState } from "@/components/ui/kanban-board";
import { useCallback, useState } from "react";
import { MotionConfig } from "motion/react";

const SAMPLE_COLUMNS: ColumnData[] = [
  {
    id: "todo",
    title: "Backlog",
    status: "todo",
    cards: [
      { id: "1", title: "Draft Q2 nurture email series", tags: [{ label: "Campaign", variant: "feature" }], assignee: { name: "Méschac Irung" }, date: "Jan 8" },
      { id: "2", title: "Fix broken UTMs on paid search ads", tags: [{ label: "Tracking", variant: "bug" }], assignee: { name: "Bernard Ngandu" }, date: "Jan 5" },
      { id: "6", title: "Refresh one-pager for enterprise pitch", tags: [{ label: "Collateral", variant: "docs" }], assignee: { name: "Anika Patel" }, date: "Jan 9" },
    ],
  },
  {
    id: "in-progress",
    title: "In flight",
    status: "in-progress",
    cards: [
      { id: "3", title: "Homepage hero & social proof block", tags: [{ label: "Creative", variant: "design" }], assignee: { name: "Théo Balick" }, date: "Jan 6" },
      { id: "7", title: "A/B test LinkedIn lead-gen forms", tags: [{ label: "Growth", variant: "improvement" }], assignee: { name: "Liam Chen" }, date: "Jan 7" },
    ],
  },
  {
    id: "done",
    title: "Launched",
    status: "done",
    cards: [{ id: "4", title: "Spring launch landing page live", tags: [{ label: "Launch", variant: "done" }], assignee: { name: "Méschac Irung" }, date: "Jan 3" }],
  },
];

export default function KanbanBoardDemo() {
  const [columns, setColumns] = useState<ColumnData[]>(SAMPLE_COLUMNS);
  const [dragState, setDragState] = useState<DragState>(null);

  const handleDrop = useCallback((cardId: string, fromColumnId: string, toColumnId: string) => {
    if (fromColumnId === toColumnId) return;
    setColumns((prev) => {
      const card = prev.find((c) => c.id === fromColumnId)?.cards.find((c) => c.id === cardId);
      if (!card) return prev;
      return prev.map((col) =>
        col.id === fromColumnId ? { ...col, cards: col.cards.filter((c) => c.id !== cardId) } : col.id === toColumnId ? { ...col, cards: [...col.cards, card] } : col,
      );
    });
  }, []);

  return (
    <MotionConfig transition={gentleSpring}>
      <div
        className="flex min-h-[500px] w-full max-w-4xl items-start justify-center px-6 py-12 antialiased"
        style={{ ["--muted" as string]: "#fff", ["--border" as string]: "rgba(0,0,0,.08)", ["--foreground" as string]: "#18181b", ["--muted-foreground" as string]: "#71717a" }}
      >
        <div className="grid w-full max-w-[520px] grid-cols-3 gap-5">
          {columns.map((col) => (
            <Column column={col} dragState={dragState} key={col.id} onDrop={handleDrop} setDragState={setDragState} />
          ))}
        </div>
      </div>
    </MotionConfig>
  );
}
