"use client";

import { BookOpen, ExternalLink, Globe, Pencil, RefreshCw, Sparkles, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { KnowledgeSections } from "@/components/knowledge/KnowledgeSections";
import { PendingChanges } from "@/components/knowledge/PendingChanges";
import { RevisionHistory } from "@/components/knowledge/RevisionHistory";
import { ScanProgress } from "@/components/knowledge/ScanProgress";
import { PROFILE_URL, REVISIONS_URL, profileApi, readTextFile, shortUrl } from "@/components/knowledge/api";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, Field, Input, Modal, Notice, PageHeader, Select, Spinner, Textarea } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { BusinessProfile, KnowledgeSection } from "@/lib/builder";
import { formatDateTime, timeAgo } from "@/lib/utils";

const STATUS: Record<BusinessProfile["status"], { label: string; tone: "gray" | "blue" | "green" | "amber" | "red" }> = {
  idle: { label: "Not scanned", tone: "gray" },
  analyzing: { label: "Scanning…", tone: "blue" },
  ready: { label: "Up to date", tone: "green" },
  limited: { label: "Partly scanned", tone: "amber" },
  failed: { label: "Scan failed", tone: "red" },
};

const MAX_UPLOAD = 1_000_000;

function normalizeUrl(v: string): string {
  const t = v.trim();
  if (!t) return "";
  return /^https?:\/\//i.test(t) ? t : `https://${t}`;
}

export default function KnowledgePage() {
  const toast = useToast();
  const { mutate: globalMutate } = useSWRConfig();
  const { data: profile, error, mutate } = useSWR<BusinessProfile>(PROFILE_URL, fetcher, {
    refreshInterval: (p) => (p?.status === "analyzing" ? 2000 : 0),
  });
  const [busy, setBusy] = useState<"rescan" | "upload" | "refresh" | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Tell the user when a scan finishes, and refresh history (scans save revisions).
  const prevStatus = useRef<BusinessProfile["status"] | undefined>(undefined);
  useEffect(() => {
    const prev = prevStatus.current;
    prevStatus.current = profile?.status;
    if (prev !== "analyzing" || !profile || profile.status === "analyzing") return;
    globalMutate(REVISIONS_URL);
    if (profile.status === "failed") toast(profile.error || "We couldn't scan your website.", "error");
    else if (profile.pending_changes.length) toast(`Scan finished — ${profile.pending_changes.length} suggested update${profile.pending_changes.length === 1 ? "" : "s"} to review`);
    else toast("Scan finished");
  }, [profile, globalMutate, toast]);

  async function run(fn: () => Promise<BusinessProfile>, success?: string): Promise<boolean> {
    try {
      const next = await fn();
      await mutate(next, false);
      globalMutate(REVISIONS_URL);
      if (success) toast(success);
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    }
  }

  async function saveSections(sections: KnowledgeSection[], message?: string) {
    if (!profile) return false;
    // Optimistic: show the change right away, roll back if the save fails.
    const before = profile;
    mutate({ ...profile, knowledge: { sections } }, false);
    const ok = await run(() => profileApi.saveKnowledge(sections), message);
    if (!ok) mutate(before, false);
    return ok;
  }

  async function onFile(file: File) {
    if (!/\.(txt|md|csv)$/i.test(file.name)) return toast("Upload a .txt, .md or .csv file", "error");
    if (file.size > MAX_UPLOAD) return toast("That file is too large (max 1 MB of text)", "error");
    setBusy("upload");
    try {
      const text = await readTextFile(file);
      if (!text.trim()) {
        toast("That file is empty", "error");
        return;
      }
      await run(() => profileApi.upload(file.name, text), `Added facts from ${file.name}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <Notice tone="red">{error.message}</Notice>;
  if (!profile)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );

  const analyzing = profile.status === "analyzing";
  const sections = profile.knowledge?.sections ?? [];
  const sectionTitles = Object.fromEntries(sections.map((s) => [s.key, s.title]));

  if (!profile.exists && !analyzing)
    return (
      <div className="mx-auto max-w-2xl">
        <PageHeader title="Business knowledge" description="What every agent knows about your business — services, hours, pricing, FAQs and more." />
        <EmptyProfile profile={profile} onAnalyze={(website) => run(() => profileApi.analyze(website))} />
      </div>
    );

  const status = STATUS[profile.status] ?? STATUS.idle;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <PageHeader title="Business knowledge" description="Shared by every agent. Keep it accurate and your agents will answer accurately." />

      {/* Business header */}
      <Card className="p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
          <div className="flex min-w-0 flex-1 gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              <BookOpen className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-base font-semibold text-zinc-900">{profile.name || "Your business"}</h2>
                <Badge tone={status.tone}>{status.label}</Badge>
                <button onClick={() => setEditOpen(true)} className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" aria-label="Edit business details">
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              </div>
              {profile.website ? (
                <a
                  href={normalizeUrl(profile.website)}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-0.5 inline-flex max-w-full items-center gap-1 text-sm text-zinc-500 hover:text-brand-700"
                >
                  <Globe className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{shortUrl(normalizeUrl(profile.website))}</span>
                  <ExternalLink className="h-3 w-3 shrink-0" />
                </a>
              ) : (
                <button onClick={() => setEditOpen(true)} className="mt-0.5 text-sm text-brand-700 hover:underline">
                  Add your website
                </button>
              )}
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500">
                <span title={formatDateTime(profile.scanned_at)}>Last scanned {profile.scanned_at ? timeAgo(profile.scanned_at) : "never"}</span>
                <span>
                  {profile.item_count} item{profile.item_count === 1 ? "" : "s"}
                </span>
                {profile.review_count > 0 && <span className="font-medium text-amber-700">{profile.review_count} need review</span>}
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:w-52 sm:shrink-0">
            <Button
              onClick={async () => {
                setBusy("rescan");
                await run(() => profileApi.rescan());
                setBusy(null);
              }}
              loading={busy === "rescan"}
              disabled={analyzing || !profile.website}
              title={!profile.website ? "Add your website first" : undefined}
            >
              {busy !== "rescan" && <RefreshCw className={analyzing ? "h-4 w-4 animate-spin" : "h-4 w-4"} />}
              {analyzing ? "Scanning…" : "Rescan website"}
            </Button>
            <label className="flex items-center gap-2 text-xs text-zinc-600">
              <span className="shrink-0">Auto-refresh</span>
              <Select
                value={profile.auto_refresh_days == null ? "" : String(profile.auto_refresh_days)}
                disabled={busy === "refresh" || !profile.website}
                onChange={async (e) => {
                  const v = e.target.value ? Number(e.target.value) : null;
                  setBusy("refresh");
                  await run(() => profileApi.update({ auto_refresh_days: v }), v ? `We'll check your website ${v === 7 ? "weekly" : "monthly"}` : "Auto-refresh off");
                  setBusy(null);
                }}
                className="h-8 text-xs"
                aria-label="Auto-refresh from website"
              >
                <option value="">Off</option>
                <option value="7">Weekly</option>
                <option value="30">Monthly</option>
              </Select>
            </label>
          </div>
        </div>
        {analyzing && (
          <div className="mt-4">
            <ScanProgress step={profile.progress_step} label={profile.progress_label} website={profile.website} />
          </div>
        )}
        {!analyzing && profile.error && (profile.status === "failed" || profile.status === "limited") && (
          <div className="mt-4">
            <Notice tone={profile.status === "failed" ? "red" : "amber"}>
              {profile.error} You can still add information by hand or upload a file below.
            </Notice>
          </div>
        )}
      </Card>

      {profile.pending_changes.length > 0 && (
        <PendingChanges
          changes={profile.pending_changes}
          sectionTitles={sectionTitles}
          onApply={async (ids) => {
            await run(() => profileApi.applyChanges(ids), "Knowledge updated");
          }}
          onDismiss={async (ids) => {
            await run(() => profileApi.dismissChanges(ids), "Suggestions dismissed");
          }}
        />
      )}

      {/* Sections */}
      <section aria-labelledby="kb-title">
        <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="kb-title" className="text-sm font-semibold text-zinc-900">
              What your agents know
            </h2>
            <p className="text-xs text-zinc-500">Edits are saved right away. Items you add or edit are never overwritten by a rescan.</p>
          </div>
          <Button size="sm" onClick={() => fileRef.current?.click()} loading={busy === "upload"}>
            {busy !== "upload" && <Upload className="h-3.5 w-3.5" />} Upload a file
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.csv,text/plain,text/markdown,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onFile(f);
              e.target.value = "";
            }}
          />
        </div>
        {sections.length === 0 ? (
          <Card className="p-6 text-center text-sm text-zinc-500">{analyzing ? "Your knowledge base will appear here when the scan finishes." : "No knowledge yet."}</Card>
        ) : (
          <KnowledgeSections key={sections.map((s) => s.key).join("|")} sections={sections} onSave={saveSections} />
        )}
      </section>

      <RevisionHistory
        onRestore={async (id) => {
          await run(() => profileApi.restore(id), "Earlier version restored");
        }}
      />

      <DetailsModal
        open={editOpen}
        profile={profile}
        onClose={() => setEditOpen(false)}
        onSave={async (body) => {
          if (await run(() => profileApi.update(body), "Business details saved")) setEditOpen(false);
        }}
      />
    </div>
  );
}

function EmptyProfile({ profile, onAnalyze }: { profile: BusinessProfile; onAnalyze: (website: string) => Promise<boolean> }) {
  const [website, setWebsite] = useState(profile.website ?? "");
  const [loading, setLoading] = useState(false);
  return (
    <Card>
      <div className="flex flex-col items-center px-6 pb-6 pt-10 text-center">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          <BookOpen className="h-6 w-6" />
        </div>
        <h2 className="text-sm font-semibold text-zinc-900">No business knowledge yet</h2>
        <p className="mt-1 max-w-sm text-sm text-zinc-500">
          Build an agent with AI to create your knowledge base, or scan your website now. Every agent will use what we find.
        </p>
        <Link
          href="/agents/new"
          className="mt-5 inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700"
        >
          <Sparkles className="h-4 w-4" /> Build an agent with AI
        </Link>
      </div>
      <div className="border-t border-zinc-100 px-5 py-5">
        {profile.status === "failed" && profile.error && (
          <div className="mb-3">
            <Notice tone="red">{profile.error}</Notice>
          </div>
        )}
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const url = normalizeUrl(website);
            if (!url) return;
            setLoading(true);
            await onAnalyze(url);
            setLoading(false);
          }}
        >
          <Field label="Or scan your website" hint="We read your public pages (about, services, team, FAQ…) and organize what we find. Nothing is invented.">
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="yourbusiness.com" inputMode="url" autoComplete="url" />
              <Button type="submit" variant="primary" loading={loading} disabled={!website.trim()} className="shrink-0">
                {!loading && <Globe className="h-4 w-4" />} Analyze
              </Button>
            </div>
          </Field>
        </form>
      </div>
    </Card>
  );
}

function DetailsModal({
  open,
  profile,
  onClose,
  onSave,
}: {
  open: boolean;
  profile: BusinessProfile;
  onClose: () => void;
  onSave: (body: { name: string; website: string; description: string }) => Promise<void>;
}) {
  const [form, setForm] = useState({ name: "", website: "", description: "" });
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (open) setForm({ name: profile.name ?? "", website: profile.website ?? "", description: profile.description ?? "" });
  }, [open, profile.name, profile.website, profile.description]);
  return (
    <Modal open={open} onClose={() => !saving && onClose()} title="Business details">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setSaving(true);
          await onSave({ ...form, website: normalizeUrl(form.website) });
          setSaving(false);
        }}
      >
        <Field label="Business name">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Website" hint="Used for rescans. Changing it doesn't remove anything until you rescan and approve the updates.">
          <Input value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} placeholder="yourbusiness.com" inputMode="url" />
        </Field>
        <Field label="Short description">
          <Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}
