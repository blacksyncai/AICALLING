"use client";

import { Check, ChevronDown, ExternalLink, FileUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Textarea } from "@/components/ui";
import { post } from "@/lib/api";
import type { BusinessProfile, KnowledgeItem, KnowledgeSection } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { put } from "./parts";

const DEFAULT_SECTIONS: [string, string][] = [
  ["overview", "Company Overview"],
  ["services", "Services and Products"],
  ["locations", "Locations and Coverage"],
  ["team", "Team Members"],
  ["hours", "Business Hours"],
  ["pricing", "Pricing and Policies"],
  ["faqs", "FAQs"],
  ["custom", "Custom Instructions"],
];

const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;

function sectionsOf(profile: BusinessProfile): KnowledgeSection[] {
  const have = profile.knowledge?.sections ?? [];
  if (have.length) return have;
  return DEFAULT_SECTIONS.map(([key, title]) => ({ key, title, items: [] }));
}

const newId = () => `k_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;

export function KnowledgeReview({ profile, onProfile }: { profile: BusinessProfile; onProfile: (p: BusinessProfile) => void }) {
  const toast = useToast();
  const sections = sectionsOf(profile);
  const [open, setOpen] = useState<Set<string>>(() => {
    const first = sections.find((s) => s.items.some((i) => i.needs_review)) ?? sections.find((s) => s.items.length);
    return new Set(first ? [first.key] : []);
  });
  const [editing, setEditing] = useState<{ section: string; id: string | null } | null>(null);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function toggle(key: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function save(nextSections: KnowledgeSection[]) {
    setSaving(true);
    try {
      const p = await put<BusinessProfile>("/api/business-profile/knowledge", { sections: nextSections });
      onProfile(p);
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    } finally {
      setSaving(false);
    }
  }

  function mapSection(key: string, fn: (items: KnowledgeItem[]) => KnowledgeItem[]) {
    return sections.map((s) => (s.key === key ? { ...s, items: fn(s.items) } : s));
  }

  async function commitEdit() {
    if (!editing) return;
    const value = text.trim();
    if (!value) {
      setEditing(null);
      return;
    }
    const { section, id } = editing;
    const next = id
      ? mapSection(section, (items) => items.map((i) => (i.id === id ? { ...i, text: value, origin: "manual" as const, needs_review: false } : i)))
      : mapSection(section, (items) => [...items, { id: newId(), text: value, source_url: null, origin: "manual" as const, needs_review: false }]);
    if (await save(next)) setEditing(null);
  }

  function startEdit(section: string, item: KnowledgeItem | null) {
    setEditing({ section, id: item?.id ?? null });
    setText(item?.text ?? "");
    setOpen((prev) => new Set(prev).add(section));
  }

  async function upload(file: File) {
    if (!/\.(txt|md|csv)$/i.test(file.name)) {
      toast("Please choose a .txt, .md or .csv file.", "error");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      toast("That file is too large. Please keep it under 2 MB.", "error");
      return;
    }
    setUploading(true);
    try {
      const content = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result ?? ""));
        reader.onerror = () => reject(new Error("Couldn't read that file."));
        reader.readAsText(file);
      });
      const p = await post<BusinessProfile>("/api/business-profile/knowledge/upload", { filename: file.name, text: content });
      onProfile(p);
      toast(`Added details from ${file.name}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const total = sections.reduce((n, s) => n + s.items.length, 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">What your agent will know</h3>
          <p className="text-xs text-zinc-500">
            {total ? `${total} facts` : "Nothing yet"}
            {profile.review_count > 0 && ` · ${profile.review_count} to double-check`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.csv,text/plain,text/markdown,text/csv"
            className="sr-only"
            tabIndex={-1}
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
          <Button size="sm" onClick={() => fileRef.current?.click()} loading={uploading}>
            {!uploading && <FileUp className="h-3.5 w-3.5" />} Upload a file
          </Button>
        </div>
      </div>

      <div className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white">
        {sections.map((s) => {
          const isOpen = open.has(s.key);
          const reviews = s.items.filter((i) => i.needs_review).length;
          return (
            <div key={s.key}>
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => toggle(s.key)}
                className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-zinc-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-500"
              >
                <span className="min-w-0 truncate text-sm font-medium text-zinc-800">{s.title}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {reviews > 0 && <Badge tone="amber">{reviews} to review</Badge>}
                  <span className="min-w-5 rounded-md bg-zinc-100 px-1.5 py-0.5 text-center text-[11px] font-medium tabular-nums text-zinc-600">
                    {s.items.length}
                  </span>
                  <ChevronDown className={cn("h-4 w-4 text-zinc-400 transition-transform", isOpen && "rotate-180")} />
                </span>
              </button>
              {isOpen && (
                <div className="space-y-1.5 bg-zinc-50/60 px-4 pb-3 pt-1">
                  {s.items.length === 0 && !(editing?.section === s.key && !editing.id) && (
                    <p className="py-1 text-xs text-zinc-500">Nothing here yet.</p>
                  )}
                  {s.items.map((item) =>
                    editing?.section === s.key && editing.id === item.id ? (
                      <EditBox key={item.id} text={text} setText={setText} onSave={commitEdit} onCancel={() => setEditing(null)} saving={saving} />
                    ) : (
                      <div key={item.id} className="group flex items-start gap-2 rounded-lg bg-white px-3 py-2 ring-1 ring-zinc-200">
                        <p className="min-w-0 flex-1 break-words text-sm leading-relaxed text-zinc-700">
                          {item.text}
                          {item.needs_review && (
                            <Badge tone="amber" className="ml-2 align-middle">
                              Review
                            </Badge>
                          )}
                        </p>
                        <span className="flex shrink-0 items-center gap-0.5">
                          {item.source_url && (
                            <a
                              href={item.source_url}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                              aria-label="Open source page"
                              title={item.source_url}
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                          {item.needs_review && (
                            <button
                              type="button"
                              disabled={saving}
                              onClick={() =>
                                save(mapSection(s.key, (items) => items.map((i) => (i.id === item.id ? { ...i, needs_review: false } : i))))
                              }
                              className="rounded-md p-1 text-zinc-400 hover:bg-emerald-50 hover:text-emerald-700"
                              aria-label="Mark as correct"
                              title="Looks right"
                            >
                              <Check className="h-3.5 w-3.5" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => startEdit(s.key, item)}
                            className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                            aria-label="Edit"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => save(mapSection(s.key, (items) => items.filter((i) => i.id !== item.id)))}
                            className="rounded-md p-1 text-zinc-400 hover:bg-red-50 hover:text-red-600"
                            aria-label="Delete"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </span>
                      </div>
                    ),
                  )}
                  {editing?.section === s.key && !editing.id ? (
                    <EditBox text={text} setText={setText} onSave={commitEdit} onCancel={() => setEditing(null)} saving={saving} />
                  ) : (
                    <button
                      type="button"
                      onClick={() => startEdit(s.key, null)}
                      className="inline-flex items-center gap-1 rounded-md px-1 py-1 text-xs font-medium text-brand-700 hover:text-brand-800"
                    >
                      <Plus className="h-3.5 w-3.5" /> Add
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EditBox({
  text,
  setText,
  onSave,
  onCancel,
  saving,
}: {
  text: string;
  setText: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  return (
    <div className="rounded-lg bg-white p-2 ring-1 ring-brand-500">
      <Textarea
        autoFocus
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSave();
          } else if (e.key === "Escape") onCancel();
        }}
        placeholder="e.g. We offer free estimates on weekdays."
        className="border-0 focus:ring-0"
      />
      <div className="mt-1 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" variant="primary" onClick={onSave} loading={saving} disabled={!text.trim()}>
          Save
        </Button>
      </div>
    </div>
  );
}
