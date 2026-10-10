"use client";

import { ArrowLeft, BookOpen, History } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  ChipInput, MIN_PATTERN_CHARS, PlaybookExplainer, ScriptBlock, TagsEditor, normalizeTags,
  type PlaybookDetail, type PlaybookTags, type PlaybookVersionFull,
} from "@/components/admin/playbooks";
import { AdminGuard } from "@/components/admin/shared";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, Spinner, Textarea, Toggle } from "@/components/ui";
import { useToast } from "@/components/toast";
import { api, fetcher, patch, post } from "@/lib/api";
import { parseDate } from "@/lib/utils";

export default function AdminPlaybookPage() {
  return (
    <AdminGuard>
      <PlaybookEditor />
    </AdminGuard>
  );
}

function when(iso: string | null) {
  const d = parseDate(iso);
  return d ? d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}

function PlaybookEditor() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { data: pb, error, mutate } = useSWR<PlaybookDetail>(id ? `/api/admin/playbooks/${id}` : null, fetcher);

  const [title, setTitle] = useState("");
  const [tags, setTags] = useState<PlaybookTags>(normalizeTags(null));
  const [patterns, setPatterns] = useState("");
  const [terms, setTerms] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState<"meta" | "version" | null>(null);
  const [viewing, setViewing] = useState<PlaybookVersionFull | null>(null);
  const [loadingVersion, setLoadingVersion] = useState<number | null>(null);

  // Load the form from the current version (again after each save).
  useEffect(() => {
    if (!pb) return;
    setTitle(pb.title);
    setTags(normalizeTags(pb.tags));
    setPatterns(pb.current?.patterns ?? "");
    setTerms(pb.current?.private_terms ?? []);
    setNote("");
  }, [pb]);

  if (error) {
    return (
      <Card>
        <EmptyState icon={<BookOpen className="h-5 w-5" />} title="Couldn't load this playbook" description={(error as Error).message} />
      </Card>
    );
  }
  if (!pb) {
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  }

  const metaDirty = title.trim() !== pb.title || JSON.stringify(tags) !== JSON.stringify(normalizeTags(pb.tags));
  const versionDirty = patterns.trim() !== (pb.current?.patterns ?? "").trim() || JSON.stringify(terms) !== JSON.stringify(pb.current?.private_terms ?? []);

  async function saveMeta(body: Partial<{ title: string; tags: PlaybookTags; active: boolean; current_version: number }>) {
    setSaving("meta");
    try {
      await mutate(await patch<PlaybookDetail>(`/api/admin/playbooks/${id}`, body), false);
      toast("Saved");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(null);
    }
  }

  async function saveVersion() {
    if (patterns.trim().length < MIN_PATTERN_CHARS) return toast(`The pattern card needs at least ${MIN_PATTERN_CHARS} characters.`, "error");
    setSaving("version");
    try {
      const updated = await post<PlaybookDetail>(`/api/admin/playbooks/${id}/versions`, { patterns, private_terms: terms, note });
      await mutate(updated, false);
      toast(`Saved as version ${updated.current_version}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(null);
    }
  }

  async function view(version: number) {
    setLoadingVersion(version);
    try {
      setViewing(await api<PlaybookVersionFull>(`/api/admin/playbooks/${id}/versions/${version}`));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setLoadingVersion(null);
    }
  }

  async function makeCurrent(version: number) {
    if (!window.confirm(`Make version ${version} the current version? New agents will use its pattern card.`)) return;
    await saveMeta({ current_version: version });
    setViewing(null);
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <Link href="/admin?tab=playbooks" className="inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-4 w-4" /> Playbooks
      </Link>
      <PlaybookExplainer />

      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="min-w-0 break-words font-display text-lg font-semibold text-zinc-900">{pb.title}</h1>
          <Badge tone="gray">v{pb.current_version}</Badge>
          <span className="font-mono text-xs text-zinc-500">{pb.slug}</span>
        </div>
        <Toggle
          label="Active"
          description="Inactive playbooks stay archived but are never used when building agents."
          checked={pb.active}
          onChange={(v) => saveMeta({ active: v })}
        />
        <Field label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} />
        </Field>
        <TagsEditor value={tags} onChange={setTags} />
        <div className="flex justify-end">
          <Button size="sm" onClick={() => saveMeta({ title: title.trim(), tags })} disabled={!metaDirty} loading={saving === "meta"}>
            Save title and tags
          </Button>
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900">Pattern card</h2>
          <p className="mt-0.5 text-xs text-zinc-500">
            The transferable methods the generator reads. Keep client names, offers, places, links and IDs out of it.
          </p>
        </div>
        <Textarea value={patterns} onChange={(e) => setPatterns(e.target.value)} rows={16} className="font-mono text-xs" aria-label="Pattern card" />
        <Field label="Private terms" hint="Client-specific names, places, links and IDs. Agents containing them are rejected unless the customer supplied the term.">
          <ChipInput value={terms} onChange={setTerms} placeholder="e.g. a client name" />
        </Field>
        <Field label="Note (optional)">
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="What changed in this version" />
        </Field>
        <div className="flex justify-end">
          <Button onClick={saveVersion} disabled={!versionDirty} loading={saving === "version"}>
            Save as new version
          </Button>
        </div>
      </Card>

      <Card className="p-5">
        <ScriptBlock label="Original script (archived verbatim, read-only)" text={pb.current?.original_text ?? ""} />
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-900">
          <History className="h-4 w-4 text-zinc-400" /> Version history
        </h2>
        <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200">
          {pb.versions.map((v) => (
            <li key={v.version} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
              <span className="font-medium tabular-nums">v{v.version}</span>
              {v.version === pb.current_version && <Badge tone="green">Current</Badge>}
              <span className="min-w-0 flex-1 truncate text-zinc-600">{v.note || "—"}</span>
              <span className="text-xs text-zinc-400">{when(v.created_at)}</span>
              <Button size="sm" variant="ghost" onClick={() => view(v.version)} loading={loadingVersion === v.version}>
                View
              </Button>
            </li>
          ))}
        </ul>
      </Card>

      <Modal open={!!viewing} onClose={() => setViewing(null)} title={viewing ? `Version ${viewing.version}` : ""} wide>
        {viewing && (
          <div className="space-y-4">
            {viewing.note && <p className="text-sm text-zinc-600">{viewing.note}</p>}
            <ScriptBlock label="Pattern card" text={viewing.patterns} />
            <div>
              <span className="mb-1.5 block text-xs font-medium text-zinc-700">Private terms</span>
              <div className="flex flex-wrap gap-1.5">
                {viewing.private_terms.length ? viewing.private_terms.map((t) => <Badge key={t} tone="gray">{t}</Badge>) : <span className="text-xs text-zinc-400">None</span>}
              </div>
            </div>
            <ScriptBlock label="Original script" text={viewing.original_text} />
            {viewing.version !== pb.current_version && (
              <div className="flex justify-end">
                <Button onClick={() => makeCurrent(viewing.version)} loading={saving === "meta"}>
                  Make current
                </Button>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
