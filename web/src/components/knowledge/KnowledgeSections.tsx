"use client";

import { Check, ChevronRight, ExternalLink, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Textarea } from "@/components/ui";
import type { KnowledgeItem, KnowledgeOrigin, KnowledgeSection } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { newItemId, shortUrl } from "./api";

const ORIGIN: Record<KnowledgeOrigin, { label: string; tone: "blue" | "gray" | "violet" }> = {
  website: { label: "Website", tone: "blue" },
  manual: { label: "Manual", tone: "gray" },
  upload: { label: "Upload", tone: "violet" },
};

type Editing = { section: string; id: string | null; text: string } | null;

/**
 * Collapsible knowledge sections. Every change is saved immediately with the full
 * knowledge shape (`onSave`), so there's no separate "save" step to forget.
 */
export function KnowledgeSections({
  sections,
  onSave,
  disabled,
}: {
  sections: KnowledgeSection[];
  onSave: (sections: KnowledgeSection[], message?: string) => Promise<boolean>;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(sections.map((s, i) => [s.key, i === 0 || s.items.some((it) => it.needs_review)])),
  );
  const [editing, setEditing] = useState<Editing>(null);
  const [saving, setSaving] = useState(false);
  const allOpen = sections.every((s) => open[s.key]);

  const withSection = (key: string, fn: (items: KnowledgeItem[]) => KnowledgeItem[]) =>
    sections.map((s) => (s.key === key ? { ...s, items: fn(s.items) } : s));

  async function commit(next: KnowledgeSection[], message?: string) {
    setSaving(true);
    const ok = await onSave(next, message);
    setSaving(false);
    return ok;
  }

  async function saveEdit() {
    if (!editing) return;
    const text = editing.text.trim();
    if (!text) return;
    const next =
      editing.id === null
        ? withSection(editing.section, (items) => [...items, { id: newItemId(), text, source_url: null, origin: "manual", needs_review: false }])
        : withSection(editing.section, (items) =>
            items.map((it) => (it.id === editing.id ? { ...it, text, origin: "manual" as const, needs_review: false } : it)),
          );
    if (await commit(next, editing.id === null ? "Added" : "Saved")) setEditing(null);
  }

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button
          className="text-xs font-medium text-zinc-500 hover:text-zinc-800"
          onClick={() => setOpen(allOpen ? {} : Object.fromEntries(sections.map((s) => [s.key, true])))}
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <div className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white">
        {sections.map((s) => {
          const isOpen = !!open[s.key];
          const review = s.items.filter((i) => i.needs_review).length;
          const addingHere = editing?.section === s.key && editing.id === null;
          return (
            <section key={s.key} aria-labelledby={`ks-${s.key}`}>
              <button
                className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-zinc-50"
                onClick={() => setOpen((o) => ({ ...o, [s.key]: !isOpen }))}
                aria-expanded={isOpen}
                aria-controls={`ks-panel-${s.key}`}
              >
                <ChevronRight className={cn("h-4 w-4 shrink-0 text-zinc-400 transition-transform", isOpen && "rotate-90")} />
                <h3 id={`ks-${s.key}`} className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-900">
                  {s.title}
                </h3>
                {review > 0 && <Badge tone="amber">{review} to review</Badge>}
                <span className="shrink-0 text-xs tabular-nums text-zinc-400">{s.items.length}</span>
              </button>
              {isOpen && (
                <div id={`ks-panel-${s.key}`} className="px-4 pb-3">
                  {s.items.length === 0 && !addingHere && <p className="py-1 text-xs text-zinc-400">Nothing here yet.</p>}
                  <ul className="space-y-1.5">
                    {s.items.map((it) => {
                      const isEditing = editing?.section === s.key && editing.id === it.id;
                      const origin = ORIGIN[it.origin] ?? ORIGIN.manual;
                      return (
                        <li
                          key={it.id}
                          className={cn("group rounded-lg border px-3 py-2", it.needs_review ? "border-amber-200 bg-amber-50/40" : "border-zinc-100 bg-zinc-50/60")}
                        >
                          {isEditing ? (
                            <ItemForm
                              value={editing.text}
                              onChange={(text) => setEditing({ ...editing, text })}
                              onCancel={() => setEditing(null)}
                              onSave={saveEdit}
                              saving={saving}
                            />
                          ) : (
                            <div className="flex items-start gap-2">
                              <div className="min-w-0 flex-1">
                                <p className="whitespace-pre-wrap break-words text-sm text-zinc-800">{it.text}</p>
                                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                  <Badge tone={origin.tone} className="px-1.5 py-0 text-[10px]">
                                    {origin.label}
                                  </Badge>
                                  {it.needs_review && (
                                    <Badge tone="amber" className="px-1.5 py-0 text-[10px]">
                                      Needs review
                                    </Badge>
                                  )}
                                  {it.source_url && (
                                    <a
                                      href={it.source_url}
                                      target="_blank"
                                      rel="noreferrer noopener"
                                      className="inline-flex min-w-0 max-w-full items-center gap-1 text-[11px] text-zinc-500 hover:text-brand-700"
                                    >
                                      <ExternalLink className="h-3 w-3 shrink-0" />
                                      <span className="truncate">{shortUrl(it.source_url)}</span>
                                    </a>
                                  )}
                                </div>
                              </div>
                              <div className="flex shrink-0 items-center gap-0.5">
                                {it.needs_review && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 px-2 text-emerald-700 hover:bg-emerald-50 hover:text-emerald-800"
                                    disabled={disabled || saving}
                                    onClick={() =>
                                      commit(
                                        withSection(s.key, (items) => items.map((x) => (x.id === it.id ? { ...x, needs_review: false } : x))),
                                        "Marked as reviewed",
                                      )
                                    }
                                    aria-label="Mark reviewed"
                                  >
                                    <Check className="h-3.5 w-3.5" />
                                    <span className="hidden sm:inline">Mark reviewed</span>
                                  </Button>
                                )}
                                <button
                                  className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-40"
                                  disabled={disabled || saving}
                                  onClick={() => setEditing({ section: s.key, id: it.id, text: it.text })}
                                  aria-label="Edit"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  className="rounded-md p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                                  disabled={disabled || saving}
                                  onClick={() => commit(withSection(s.key, (items) => items.filter((x) => x.id !== it.id)), "Deleted")}
                                  aria-label="Delete"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                  {addingHere ? (
                    <div className="mt-1.5 rounded-lg border border-zinc-200 px-3 py-2">
                      <ItemForm
                        value={editing.text}
                        onChange={(text) => setEditing({ ...editing, text })}
                        onCancel={() => setEditing(null)}
                        onSave={saveEdit}
                        saving={saving}
                        placeholder={`Add to ${s.title.toLowerCase()}…`}
                      />
                    </div>
                  ) : (
                    <button
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-600 disabled:opacity-40"
                      disabled={disabled}
                      onClick={() => setEditing({ section: s.key, id: null, text: "" })}
                    >
                      <Plus className="h-3.5 w-3.5" /> Add item
                    </button>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function ItemForm({
  value,
  onChange,
  onSave,
  onCancel,
  saving,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  placeholder?: string;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
      className="space-y-2"
    >
      <Textarea
        autoFocus
        rows={Math.min(8, Math.max(2, value.split("\n").length))}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            onSave();
          }
        }}
        placeholder={placeholder}
        className="text-sm"
        aria-label="Knowledge item"
      />
      <div className="flex gap-2">
        <Button size="sm" variant="primary" type="submit" loading={saving} disabled={!value.trim()}>
          Save
        </Button>
        <Button size="sm" variant="ghost" type="button" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
