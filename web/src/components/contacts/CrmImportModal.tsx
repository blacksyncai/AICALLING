"use client";

import { Ban, CheckCircle2, Download, PhoneOff, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Badge, Button, Field, Input, Modal, Notice, Select, Spinner, Toggle } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import { cn } from "@/lib/utils";

interface FilterDef {
  key: string;
  label: string;
  type: "multi" | "single";
  free?: boolean;
  options: { value: string; label: string }[];
}
interface Preview {
  found: number;
  will_import: number;
  already_in_blacksync: number;
  do_not_call: number;
  contacted: number;
  skipped_contacted: number;
  sample: { name: string; phone: string; stage: string; tags: string[]; dnc: boolean; contacted: boolean | null }[];
}
interface Overview {
  providers: { key: string; name: string; can_import: boolean }[];
  connections: { provider: string; account_label: string }[];
}

const errText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

function MultiPicker({ f, value, onChange }: { f: FilterDef; value: string[]; onChange: (v: string[]) => void }) {
  const [q, setQ] = useState("");
  const shown = f.options.filter((o) => !q || o.label.toLowerCase().includes(q.toLowerCase()));
  const extra = value.filter((v) => !f.options.some((o) => o.value === v));
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium text-zinc-700">{f.label}</span>
        {value.length > 0 && (
          <button type="button" onClick={() => onChange([])} className="text-xs text-zinc-400 hover:text-zinc-700">
            Clear ({value.length})
          </button>
        )}
      </div>
      {(f.options.length > 10 || f.free) && (
        <div className="relative mb-2">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && f.free && q.trim()) {
                e.preventDefault();
                if (!value.includes(q.trim())) onChange([...value, q.trim()]);
                setQ("");
              }
            }}
            placeholder={f.free ? `Search or type a ${f.label.toLowerCase().replace(/s$/, "")} and press Enter` : `Search ${f.label.toLowerCase()}`}
            className="h-8 pl-8 text-sm"
          />
        </div>
      )}
      <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto">
        {[...extra.map((v) => ({ value: v, label: v })), ...shown].map((o) => {
          const on = value.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => toggle(o.value)}
              aria-pressed={on}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs transition-colors",
                on ? "border-brand-500 bg-brand-50 font-medium text-brand-700" : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300",
              )}
            >
              {o.label}
            </button>
          );
        })}
        {!shown.length && !extra.length && <span className="text-xs text-zinc-400">No matches</span>}
      </div>
    </div>
  );
}

export function CrmImportModal({ open, onClose, onDone, initialKey }: { open: boolean; onClose: () => void; onDone: () => void; initialKey?: string }) {
  const { data: overview } = useSWR<Overview>(open ? "/api/integrations/crm" : null, fetcher);
  const crms = useMemo(() => {
    if (!overview) return [];
    const importable = new Set(overview.providers.filter((p) => p.can_import).map((p) => p.key));
    const names = Object.fromEntries(overview.providers.map((p) => [p.key, p.name]));
    return overview.connections.filter((c) => importable.has(c.provider)).map((c) => ({ key: c.provider, name: names[c.provider], label: c.account_label }));
  }, [overview]);
  const [key, setKey] = useState<string>(initialKey ?? "");
  useEffect(() => {
    if (initialKey) setKey(initialKey);
  }, [initialKey]);
  const active = key || crms[0]?.key || "";
  const { data: opts, error: optsError } = useSWR<{ filters: FilterDef[] }>(open && active ? `/api/integrations/crm/${active}/import/options` : null, fetcher);
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [skipContacted, setSkipContacted] = useState(false);
  const [listTag, setListTag] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<string>("");

  const body = useMemo(() => ({ filters, skip_contacted: skipContacted, list_tag: listTag }), [filters, skipContacted, listTag]);

  useEffect(() => {
    setFilters({});
    setPreview(null);
    setDone("");
  }, [active]);

  useEffect(() => {
    if (!open || !active) return;
    let cancelled = false;
    setPreviewing(true);
    setErr("");
    const t = window.setTimeout(async () => {
      try {
        const p = await post<Preview>(`/api/integrations/crm/${active}/import/preview`, { filters, skip_contacted: skipContacted });
        if (!cancelled) setPreview(p);
      } catch (e) {
        if (!cancelled) setErr(errText(e));
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 600);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [open, active, filters, skipContacted]);

  const run = async () => {
    setImporting(true);
    setErr("");
    try {
      const r = await post<{ created: number; linked: number; do_not_call: number; skipped_contacted: number }>(`/api/integrations/crm/${active}/import`, body);
      setDone(
        `Imported ${r.created} new contact${r.created === 1 ? "" : "s"}` +
          (r.linked ? `, updated ${r.linked}` : "") +
          (r.do_not_call ? ` · ${r.do_not_call} on do-not-call (saved, never dialed)` : "") +
          (r.skipped_contacted ? ` · skipped ${r.skipped_contacted} already contacted` : "") +
          ".",
      );
      onDone();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setImporting(false);
    }
  };

  const name = crms.find((c) => c.key === active)?.name ?? "CRM";

  return (
    <Modal open={open} onClose={onClose} title="Import from CRM" wide>
      {!overview ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : crms.length === 0 ? (
        <div className="space-y-3 text-sm text-zinc-600">
          <p>Connect Follow Up Boss, Close, HubSpot, GoHighLevel, Pipedrive, Salesforce or another CRM first, then import the exact people you want to call.</p>
          <Link href="/integrations" className="font-medium text-brand-600 hover:underline">
            Go to Integrations →
          </Link>
        </div>
      ) : (
        <div className="space-y-5">
          {crms.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {crms.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => setKey(c.key)}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm",
                    c.key === active ? "border-brand-500 bg-brand-50 font-medium text-brand-700" : "border-zinc-200 text-zinc-600 hover:border-zinc-300",
                  )}
                >
                  {c.name}
                </button>
              ))}
            </div>
          )}

          {optsError ? (
            <Notice tone="red">Couldn&apos;t load {name} filters: {(optsError as Error).message}</Notice>
          ) : !opts ? (
            <div className="flex items-center gap-2 text-sm text-zinc-500">
              <Spinner /> Loading {name} stages, tags and lists…
            </div>
          ) : opts.filters.length === 0 ? (
            <p className="text-sm text-zinc-500">{name} has no filters to choose from; everyone with a phone number will be imported.</p>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {opts.filters.map((f) =>
                f.type === "multi" ? (
                  <MultiPicker key={f.key} f={f} value={filters[f.key] ?? []} onChange={(v) => setFilters({ ...filters, [f.key]: v })} />
                ) : (
                  <Field key={f.key} label={f.label}>
                    <Select value={filters[f.key]?.[0] ?? ""} onChange={(e) => setFilters({ ...filters, [f.key]: e.target.value ? [e.target.value] : [] })}>
                      <option value="">Any</option>
                      {f.options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                ),
              )}
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-2">
            <Toggle
              checked={skipContacted}
              onChange={setSkipContacted}
              label="Skip people already contacted"
              description={`Leave out anyone ${name} shows you've already called, texted or emailed.`}
            />
            <Field label="Tag imported contacts (optional)" hint="Use it to filter them or add them to a campaign.">
              <Input value={listTag} maxLength={60} placeholder={`e.g. ${name} hot buyers`} onChange={(e) => setListTag(e.target.value)} />
            </Field>
          </div>

          <div className="rounded-xl border border-zinc-200 bg-zinc-50/60 p-4">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
              {previewing && !preview ? (
                <span className="flex items-center gap-2 text-zinc-500">
                  <Spinner /> Counting matches in {name}…
                </span>
              ) : preview ? (
                <>
                  <span className="font-semibold text-zinc-900">
                    {preview.will_import.toLocaleString()} new contact{preview.will_import === 1 ? "" : "s"} to import
                  </span>
                  <span className="text-zinc-500">{preview.found.toLocaleString()} matched</span>
                  {preview.already_in_blacksync > 0 && <span className="text-zinc-500">{preview.already_in_blacksync} already in BlackSync</span>}
                  {preview.do_not_call > 0 && (
                    <span className="flex items-center gap-1 text-red-600">
                      <Ban className="h-3.5 w-3.5" /> {preview.do_not_call} do-not-call (won&apos;t be dialed)
                    </span>
                  )}
                  {preview.contacted > 0 && (
                    <span className="flex items-center gap-1 text-amber-700">
                      <PhoneOff className="h-3.5 w-3.5" /> {preview.contacted} already contacted
                      {preview.skipped_contacted ? " (skipped)" : ""}
                    </span>
                  )}
                  {previewing && <Spinner className="h-3.5 w-3.5" />}
                </>
              ) : null}
            </div>
            {preview && preview.sample.length > 0 && (
              <ul className="mt-3 divide-y divide-zinc-100 rounded-lg bg-white text-sm ring-1 ring-zinc-100">
                {preview.sample.map((c) => (
                  <li key={c.phone + c.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                    <span className="min-w-0 flex-1 truncate font-medium text-zinc-800">{c.name || "Unnamed"}</span>
                    <span className="font-mono text-xs text-zinc-500">{c.phone}</span>
                    {c.stage && <Badge tone="gray">{c.stage}</Badge>}
                    {c.tags.slice(0, 2).map((t) => (
                      <Badge key={t} tone="blue">
                        {t}
                      </Badge>
                    ))}
                    {c.dnc && <Badge tone="red">Do not call</Badge>}
                    {c.contacted && <Badge tone="amber">Contacted</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {err && <Notice tone="red">{err}</Notice>}
          {done && (
            <Notice tone="green">
              <span className="inline-flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4" /> {done}
              </span>
            </Notice>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              {done ? "Close" : "Cancel"}
            </Button>
            <Button variant="primary" loading={importing} disabled={!preview || preview.found === 0} onClick={() => void run()}>
              <Download className="h-4 w-4" /> Import {preview ? preview.will_import.toLocaleString() : ""} contacts
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
