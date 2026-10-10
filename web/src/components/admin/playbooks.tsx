"use client";

import { BookOpen, Check, Copy, Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type KeyboardEvent } from "react";
import useSWR from "swr";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, Notice, Spinner, Textarea } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher, post } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

export type PlaybookTags = { verticals: string[]; directions: string[]; goals: string[]; styles: string[] };

export type PlaybookSummary = {
  id: string;
  slug: string;
  title: string;
  tags: Partial<PlaybookTags>;
  active: boolean;
  current_version: number;
};

export type PlaybookVersionMeta = {
  version: number;
  note: string;
  private_terms: string[];
  created_at: string | null;
  original_chars: number;
  pattern_chars: number;
};

export type PlaybookVersionFull = PlaybookVersionMeta & { original_text: string; patterns: string };

export type PlaybookDetail = PlaybookSummary & {
  updated_at: string | null;
  current: PlaybookVersionFull | null;
  versions: PlaybookVersionMeta[];
};

export const TAG_FIELDS: { key: keyof PlaybookTags; label: string; hint: string; placeholder: string }[] = [
  { key: "verticals", label: "Industries", hint: "Matched against the customer's industry.", placeholder: "real_estate" },
  { key: "directions", label: "Call direction", hint: "outbound, inbound or both.", placeholder: "outbound" },
  { key: "goals", label: "Goals", hint: "What the call is for, e.g. book_meeting.", placeholder: "book_meeting" },
  { key: "styles", label: "Tone", hint: "Words that describe how the agent sounds.", placeholder: "calm" },
];

export const EMPTY_TAGS: PlaybookTags = { verticals: [], directions: [], goals: [], styles: [] };

export const normalizeTags = (t: Partial<PlaybookTags> | null | undefined): PlaybookTags => ({
  verticals: t?.verticals ?? [],
  directions: t?.directions ?? [],
  goals: t?.goals ?? [],
  styles: t?.styles ?? [],
});

export const MIN_PATTERN_CHARS = 50;

/** The line shown above every playbook screen. */
export function PlaybookExplainer() {
  return (
    <Notice tone="blue">
      Playbooks are internal reference scripts — customers never see them. When we build an agent, only the <span className="font-medium">pattern card</span> is
      used; the original script is kept here for reference only.
    </Notice>
  );
}

// ── Chip editor ──────────────────────────────────────────────────────────────

/** A list of short values. Type and press Enter or comma to add; paste a comma list to add many. */
export function ChipInput({
  value,
  onChange,
  placeholder,
  lowercase,
  tone = "gray",
  ariaLabel,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  lowercase?: boolean;
  tone?: "gray" | "red";
  ariaLabel?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const parts = raw
      .split(/[,\n]/)
      .map((s) => (lowercase ? s.trim().toLowerCase() : s.trim()))
      .filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    for (const p of parts) if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p);
    onChange(next);
    setDraft("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div className="flex min-h-9 w-full min-w-0 flex-wrap items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2 py-1.5 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
      {value.map((v) => (
        <span
          key={v}
          className={cn(
            "inline-flex max-w-full items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
            tone === "red" ? "bg-red-50 text-red-700" : "bg-zinc-100 text-zinc-700",
          )}
        >
          <span className="min-w-0 break-all">{v}</span>
          <button
            type="button"
            onClick={() => onChange(value.filter((x) => x !== v))}
            className="shrink-0 rounded text-zinc-400 hover:text-zinc-800"
            aria-label={`Remove ${v}`}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => {
          const v = e.target.value;
          if (v.includes(",")) add(v);
          else setDraft(v);
        }}
        onKeyDown={onKey}
        onBlur={() => add(draft)}
        placeholder={value.length ? "" : placeholder}
        aria-label={ariaLabel}
        className="h-6 min-w-[6rem] flex-1 bg-transparent px-1 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none"
      />
    </div>
  );
}

export function TagsEditor({ value, onChange }: { value: PlaybookTags; onChange: (v: PlaybookTags) => void }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {TAG_FIELDS.map((f) => (
        <div key={f.key} className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-zinc-700">{f.label}</div>
          <ChipInput
            value={value[f.key]}
            onChange={(v) => onChange({ ...value, [f.key]: v })}
            placeholder={`e.g. ${f.placeholder}`}
            lowercase
            ariaLabel={f.label}
          />
          <div className="mt-1 text-xs text-zinc-500">{f.hint}</div>
        </div>
      ))}
    </div>
  );
}

export function TagBadges({ tags, className }: { tags: Partial<PlaybookTags>; className?: string }) {
  const t = normalizeTags(tags);
  const all = [
    ...t.verticals.map((v) => ({ v, tone: "brand" as const })),
    ...t.directions.map((v) => ({ v, tone: "blue" as const })),
    ...t.goals.map((v) => ({ v, tone: "violet" as const })),
    ...t.styles.map((v) => ({ v, tone: "gray" as const })),
  ];
  if (!all.length) return <span className="text-xs text-zinc-400">No tags</span>;
  return (
    <div className={cn("flex min-w-0 flex-wrap gap-1", className)}>
      {all.map((x, i) => (
        <Badge key={`${x.v}-${i}`} tone={x.tone} className="max-w-full break-all">
          {x.v}
        </Badge>
      ))}
    </div>
  );
}

// ── Script block ─────────────────────────────────────────────────────────────

/** A long read-only text in a scrollable monospace block, with a copy button. */
export function ScriptBlock({ text, label, emptyText = "Nothing here." }: { text: string; label: string; emptyText?: string }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast("Couldn't copy — select the text and copy it manually", "error");
    }
  };
  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-zinc-700">{label}</span>
        <button
          type="button"
          onClick={copy}
          disabled={!text}
          className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 text-xs font-medium text-zinc-800 hover:bg-zinc-50 disabled:opacity-50"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="max-h-96 min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-relaxed text-zinc-800">
        {text || <span className="text-zinc-400">{emptyText}</span>}
      </pre>
    </div>
  );
}

// ── List (admin tab) ─────────────────────────────────────────────────────────

export function PlaybooksTab() {
  const [creating, setCreating] = useState(false);
  const { data, error, mutate } = useSWR<{ playbooks: PlaybookSummary[] }>("/api/admin/playbooks", fetcher);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <PlaybookExplainer />
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> New playbook
        </Button>
      </div>

      <Card className="min-w-0">
        {error ? (
          <EmptyState icon={<BookOpen className="h-5 w-5" />} title="Couldn't load playbooks" description={error.message} />
        ) : !data ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : data.playbooks.length === 0 ? (
          <EmptyState
            icon={<BookOpen className="h-5 w-5" />}
            title="No playbooks yet"
            description="Add a proven call script so new agents can learn from it."
            action={
              <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New playbook
              </Button>
            }
          />
        ) : (
          <ul className="divide-y divide-zinc-100">
            {data.playbooks.map((p) => (
              <li key={p.id}>
                <Link href={`/admin/playbooks/${p.id}`} className="flex min-w-0 flex-col gap-2 px-5 py-4 hover:bg-zinc-50 sm:flex-row sm:items-center sm:gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="min-w-0 break-words font-medium text-zinc-900">{p.title}</span>
                      <Badge tone={p.active ? "green" : "gray"}>{p.active ? "Active" : "Inactive"}</Badge>
                      <Badge tone="gray">v{p.current_version}</Badge>
                    </div>
                    <div className="mt-0.5 truncate font-mono text-xs text-zinc-500">{p.slug}</div>
                  </div>
                  <TagBadges tags={p.tags} className="sm:max-w-[50%] sm:justify-end" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <NewPlaybookModal open={creating} onClose={() => setCreating(false)} onCreated={() => void mutate()} />
    </div>
  );
}

// ── New playbook modal ───────────────────────────────────────────────────────

const SLUG_RE = /^[a-z][a-z0-9_]{2,79}$/;

const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^[^a-z]+/, "")
    .replace(/_+$/, "")
    .slice(0, 80);

export function NewPlaybookModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [tags, setTags] = useState<PlaybookTags>(EMPTY_TAGS);
  const [original, setOriginal] = useState("");
  const [patterns, setPatterns] = useState("");
  const [terms, setTerms] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const effectiveSlug = slugTouched ? slug : slugify(title);
  const slugOk = SLUG_RE.test(effectiveSlug);
  const patternsOk = patterns.trim().length >= MIN_PATTERN_CHARS;
  const canSave = title.trim().length >= 2 && slugOk && original.trim().length > 0 && patternsOk;

  const reset = () => {
    setTitle("");
    setSlug("");
    setSlugTouched(false);
    setTags(EMPTY_TAGS);
    setOriginal("");
    setPatterns("");
    setTerms([]);
    setNote("");
  };

  const close = () => {
    if (saving) return;
    onClose();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    try {
      const created = await post<PlaybookDetail>("/api/admin/playbooks", {
        slug: effectiveSlug,
        title: title.trim(),
        tags,
        original_text: original,
        patterns: patterns.trim(),
        private_terms: terms,
        note: note.trim(),
      });
      toast(`Created “${created.title}”`);
      onCreated();
      onClose();
      reset();
      router.push(`/admin/playbooks/${created.id}`);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={close} title="New playbook" wide>
      <form onSubmit={submit} className="flex min-w-0 flex-col gap-4">
        <PlaybookExplainer />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Title *">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Real estate SDR" required autoFocus />
          </Field>
          <Field
            label="Short ID *"
            hint={
              effectiveSlug && !slugOk ? (
                <span className="text-red-600">Lowercase letters, numbers and underscores; starts with a letter; at least 3 characters.</span>
              ) : (
                "Used internally. Can't be changed later."
              )
            }
          >
            <Input
              value={effectiveSlug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(e.target.value.toLowerCase());
              }}
              placeholder="real_estate_sdr"
              className="font-mono"
              autoComplete="off"
            />
          </Field>
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold text-zinc-900">Tags</div>
          <TagsEditor value={tags} onChange={setTags} />
        </div>

        <Field label="Original script *" hint="Paste the client's script exactly as written. It's archived as-is and never used to build agents.">
          <Textarea value={original} onChange={(e) => setOriginal(e.target.value)} rows={8} className="font-mono text-xs" placeholder="Paste the full script…" />
        </Field>

        <Field
          label="Pattern card *"
          hint={
            <>
              The cleaned-up version with no client names, places or links. This is what the agent builder reads.{" "}
              <span className={cn(!patternsOk && patterns.length > 0 && "text-red-600")}>
                {patterns.trim().length.toLocaleString()} characters (minimum {MIN_PATTERN_CHARS}).
              </span>
            </>
          }
        >
          <Textarea value={patterns} onChange={(e) => setPatterns(e.target.value)} rows={8} className="font-mono text-xs" />
        </Field>

        <div className="min-w-0">
          <div className="mb-1.5 text-xs font-medium text-zinc-700">Private terms</div>
          <ChipInput value={terms} onChange={setTerms} tone="red" placeholder="Client names, places, websites…" ariaLabel="Private terms" />
          <div className="mt-1 text-xs text-zinc-500">These words must never show up in another customer&apos;s agent. Press Enter or comma after each one.</div>
        </div>

        <Field label="Note">
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Where this script came from" maxLength={500} />
        </Field>

        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={close} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={saving} disabled={!canSave}>
            Create playbook
          </Button>
        </div>
      </form>
    </Modal>
  );
}
