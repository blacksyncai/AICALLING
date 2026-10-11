"use client";

import { ArrowLeft, Download, FileSpreadsheet, Play, Trash2, Upload, UserPlus } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Notice, Spinner } from "@/components/ui";
import { api, del, fetcher, post } from "@/lib/api";
import { sessionToken } from "@/lib/clerk";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { AddCredits } from "./CreditsCard";
import { ResultPanel } from "./ResultPanel";
import type { BatchDetail, BatchPreview, LeadFinderUsage, Lookup, LookupBatch } from "./types";

const MAX_BYTES = 2 * 1024 * 1024;
const TEMPLATE = "Address,City,State,Zip\n1252 E 21st St,Erie,PA,16503\n";
const PAGE = 50;

const STATUS: Record<LookupBatch["status"], { label: string; tone: "gray" | "blue" | "green" | "red" }> = {
  draft: { label: "Not started", tone: "gray" },
  running: { label: "Running", tone: "blue" },
  done: { label: "Done", tone: "green" },
  failed: { label: "Stopped", tone: "red" },
};

function fmtDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Bulk tab: upload a CSV of addresses, see the cost, run it, then review/export/save the results. */
export function BulkLookup({ usage, onUsage }: { usage: LeadFinderUsage | undefined; onUsage: () => void }) {
  const toast = useToast();
  const [preview, setPreview] = useState<BatchPreview | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showSkipped, setShowSkipped] = useState(false);
  const { session } = useSession();
  const isAdmin = !!session?.user.is_superadmin;

  /** After credits are added, refresh the balance and whether the draft can start. */
  async function recheck() {
    onUsage();
    if (!preview) return;
    try {
      const u = await api<LeadFinderUsage>("/api/lead-finder/usage");
      const byCredits = u.unlimited || u.credits >= preview.max_credits;
      const byBalance = u.price_cents != null && u.balance_cents >= preview.max_credits * u.price_cents;
      setPreview({ ...preview, usage: u, enough_credits: byCredits || byBalance, pay_with: byCredits ? "credits" : "balance",
                   price_cents: u.price_cents, max_total_cents: byCredits || u.price_cents == null ? 0 : preview.max_credits * u.price_cents });
    } catch {
      /* the balance refreshes on its own */
    }
  }
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: batches, mutate: refreshBatches } = useSWR<{ items: LookupBatch[] }>("/api/lead-finder/batches", fetcher, {
    refreshInterval: (d) => (d?.items.some((b) => b.status === "running") ? 3000 : 0),
  });

  async function upload(file: File) {
    if (file.size > MAX_BYTES) return toast("That file is over 2 MB. Split it into smaller files.", "error");
    setBusy(true);
    try {
      setPreview(await post<BatchPreview>("/api/lead-finder/batches", { filename: file.name, text: await file.text() }));
      setShowSkipped(false);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function start() {
    if (!preview) return;
    const paid = preview.pay_with === "balance" && preview.new_rows > 0 && preview.price_cents != null;
    if (paid) {
      const each = `$${((preview.price_cents ?? 0) / 100).toFixed(2)}`;
      const policy = (preview.usage ?? usage)?.policy === "completed" ? "every completed lookup" : "each owner found";
      if (!window.confirm(`Run ${preview.new_rows.toLocaleString()} paid lookups at ${each} for ${policy}? ` +
        `Up to $${(preview.max_total_cents / 100).toFixed(2)} is set aside from your lookup balance and anything not used is returned.`)) return;
    }
    setBusy(true);
    try {
      await post(`/api/lead-finder/batches/${preview.id}/start`, paid ? { expected_price_cents: preview.price_cents } : {});
      setOpenId(preview.id);
      setPreview(null);
      refreshBatches();
      onUsage();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (preview) await del(`/api/lead-finder/batches/${preview.id}`).catch(() => undefined);
    setPreview(null);
  }

  if (openId) {
    return (
      <BatchView
        id={openId}
        onBack={() => {
          setOpenId(null);
          refreshBatches();
        }}
        onUsage={onUsage}
      />
    );
  }

  const disabled = !usage || !usage.enabled || !usage.configured;
  return (
    <div className="space-y-4">
      {usage && !usage.enabled && <Notice tone="amber">Lead Finder isn&apos;t enabled for this account. Contact your BlackSync admin.</Notice>}
      {usage && usage.enabled && !usage.configured && <Notice tone="amber">Property lookup is temporarily unavailable. Please try again later.</Notice>}

      {!preview ? (
        <Card className="p-5">
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-zinc-300 px-4 py-8 text-center">
            <FileSpreadsheet className="h-6 w-6 text-zinc-400" />
            <div>
              <p className="text-sm font-medium text-zinc-900">Upload a CSV of property addresses</p>
              <p className="mt-0.5 text-xs text-zinc-500">
                Columns: Address, City, State, Zip — or one Full Address column. Up to 1,000 rows. Other columns are ignored.
              </p>
            </div>
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" onClick={() => fileRef.current?.click()} loading={busy} disabled={disabled}>
                <Upload className="h-4 w-4" /> Choose CSV
              </Button>
              <Button variant="ghost" onClick={() => saveBlob(new Blob([TEMPLATE], { type: "text/csv" }), "lead-finder-template.csv")}>
                <Download className="h-4 w-4" /> Template
              </Button>
            </div>
            <p className="text-xs text-zinc-400">Nothing is looked up until you review the cost and press Start.</p>
          </div>
        </Card>
      ) : (
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="min-w-0 truncate text-sm font-semibold text-zinc-900">{preview.filename}</h3>
            <span className="text-xs text-zinc-500">{preview.total_rows.toLocaleString()} rows in file</span>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Stat label="Ready to look up" value={preview.new_rows} />
            <Stat label="Already looked up (free)" value={preview.cached_rows} />
            <Stat label="Skipped" value={preview.invalid.length} />
            {preview.pay_with === "balance" ? (
              <Stat
                label="Max cost"
                value={`$${(preview.max_total_cents / 100).toFixed(2)}`}
                hint={preview.price_cents != null ? `$${(preview.price_cents / 100).toFixed(2)} each · balance $${(((preview.usage ?? usage)?.balance_cents ?? 0) / 100).toFixed(2)}` : "Paid lookups are off"}
              />
            ) : (
              <Stat label="Credits (max)" value={preview.max_credits} hint={(preview.usage ?? usage)?.unlimited ? "Unlimited" : `You have ${((preview.usage ?? usage)?.credits ?? 0).toLocaleString()}`} />
            )}
          </dl>
          <p className="mt-3 text-xs text-zinc-500">
            {(preview.usage ?? usage)?.policy === "completed"
              ? "Every completed lookup is charged; errors are returned when the run finishes."
              : "Only owners found are charged — misses and errors are returned when the run finishes."}{" "}
            Free daily lookups apply to single addresses only.
          </p>
          {preview.invalid.length > 0 && (
            <div className="mt-3">
              <button className="text-xs font-medium text-zinc-600 underline" onClick={() => setShowSkipped((v) => !v)}>
                {showSkipped ? "Hide" : "Show"} skipped rows
              </button>
              {showSkipped && (
                <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded-lg bg-zinc-50 p-3 text-xs text-zinc-600">
                  {preview.invalid.map((i) => (
                    <li key={i.row}>
                      <span className="font-medium tabular-nums text-zinc-800">Row {i.row}:</span> {i.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {!preview.enough_credits && (
            <div className="mt-3 space-y-2">
              <Notice tone="amber">
                {preview.price_cents != null ? (
                  <>
                    This file costs up to ${((preview.max_credits * preview.price_cents) / 100).toFixed(2)} and your lookup balance is $
                    {(((preview.usage ?? usage)?.balance_cents ?? 0) / 100).toFixed(2)}.{" "}
                    <Link href="/billing?tab=lookups" className="font-medium underline">
                      Add funds
                    </Link>{" "}
                    or upload fewer addresses.
                  </>
                ) : (
                  <>
                    This file needs up to {preview.max_credits.toLocaleString()} lookup credits and you have {usage?.credits.toLocaleString() ?? 0}.{" "}
                    {isAdmin ? "Add credits, then start." : "Upload fewer addresses, or ask your BlackSync admin for more."}
                  </>
                )}
              </Notice>
              {isAdmin && session?.org && (
                <div className="max-w-xs">
                  <AddCredits orgId={session.org.id} compact onAdded={recheck} />
                </div>
              )}
            </div>
          )}
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={cancel} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" onClick={start} loading={busy} disabled={!preview.enough_credits || disabled}>
              <Play className="h-4 w-4" /> Start {preview.new_rows + preview.cached_rows} lookups
            </Button>
          </div>
        </Card>
      )}

      <h2 className="mt-6 text-sm font-semibold text-zinc-900">Bulk lookups</h2>
      <Card className="min-w-0">
        {!batches ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : batches.items.length === 0 ? (
          <EmptyState icon={<FileSpreadsheet className="h-5 w-5" />} title="No bulk lookups yet" description="Upload a CSV above; each run is kept here." />
        ) : (
          <ul className="divide-y divide-zinc-100">
            {batches.items.map((b) => (
              <li key={b.id}>
                <button onClick={() => setOpenId(b.id)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-zinc-50">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-900">{b.filename}</span>
                  <Badge tone={STATUS[b.status].tone}>{STATUS[b.status].label}</Badge>
                  <span className="text-xs tabular-nums text-zinc-500">
                    {b.matched.toLocaleString()} found · {b.processed.toLocaleString()} done · {b.pay_source === "balance" ? `$${((b.charged_cents ?? 0) / 100).toFixed(2)}` : `${b.credits_used.toLocaleString()} credits`}
                  </span>
                  <span className="text-xs text-zinc-400">{fmtDate(b.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-lg bg-zinc-50 px-3 py-2">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="font-display text-lg font-semibold tabular-nums text-zinc-900">{typeof value === "number" ? value.toLocaleString() : value}</dd>
      {hint && <dd className="text-[11px] text-zinc-400">{hint}</dd>}
    </div>
  );
}

function BatchView({ id, onBack, onUsage }: { id: string; onBack: () => void; onUsage: () => void }) {
  const toast = useToast();
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<Lookup | null>(null);
  const [saving, setSaving] = useState(false);
  const { data, mutate } = useSWR<BatchDetail>(`/api/lead-finder/batches/${id}?offset=${page * PAGE}&limit=${PAGE}`, fetcher, {
    refreshInterval: (d) => (d?.status === "running" ? 2000 : 0),
  });
  const running = data?.status === "running";
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) onUsage();
    wasRunning.current = running;
  }, [running, onUsage]);

  async function exportCsv() {
    const token = await sessionToken();
    const res = await fetch(`/api/lead-finder/batches/${id}/export`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) return toast("Couldn't download the results.", "error");
    saveBlob(await res.blob(), `${(data?.filename ?? "lookup").replace(/\.csv$/i, "")}-results.csv`);
  }

  async function saveAll() {
    setSaving(true);
    try {
      const r = await post<{ created: number; updated: number }>(`/api/lead-finder/batches/${id}/save-leads`);
      toast(`${r.created} added to Contacts${r.updated ? `, ${r.updated} already there (updated)` : ""}`);
      mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm("Delete the contact details from this batch? Credits already used aren't returned.")) return;
    try {
      await del(`/api/lead-finder/batches/${id}`);
      toast("Batch results deleted");
      mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function view(l: Lookup) {
    try {
      setOpen(await api<Lookup>(`/api/lead-finder/lookups/${l.id}`));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  if (!data) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }
  const total = Math.max(1, data.processed + (running ? Math.max(0, data.valid - data.processed) : 0));
  const pct = Math.min(100, (data.processed / Math.max(1, data.valid || total)) * 100);
  const pages = Math.ceil((data.valid || data.processed) / PAGE);

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-4 w-4" /> All bulk lookups
      </button>
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-900">{data.filename}</h3>
          <Badge tone={STATUS[data.status].tone}>{STATUS[data.status].label}</Badge>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-100">
          <div className={cn("h-full rounded-full transition-all", data.status === "failed" ? "bg-red-500" : "bg-brand-600")} style={{ width: `${pct}%` }} />
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat label="Done" value={data.processed} />
          <Stat label="Owners found" value={data.matched} />
          <Stat label="No match" value={data.no_match} />
          <Stat label="Failed (free)" value={data.failed} />
          {data.pay_source === "balance" ? (
            <Stat label="Charged" value={`$${((data.charged_cents ?? 0) / 100).toFixed(2)}`} />
          ) : (
            <Stat label="Credits used" value={data.credits_used} />
          )}
        </dl>
        {data.error && (
          <div className="mt-3">
            <Notice tone="red">{data.error}</Notice>
          </div>
        )}
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={remove} disabled={running}>
            <Trash2 className="h-3.5 w-3.5" /> Delete results
          </Button>
          <Button variant="secondary" size="sm" onClick={exportCsv} disabled={running}>
            <Download className="h-3.5 w-3.5" /> Download CSV
          </Button>
          <Button variant="primary" size="sm" onClick={saveAll} loading={saving} disabled={running || data.matched === 0}>
            <UserPlus className="h-3.5 w-3.5" /> Save found owners to Contacts
          </Button>
        </div>
      </Card>

      {open && <ResultPanel lookup={open} cached saving={false} onSave={() => void post(`/api/lead-finder/lookups/${open.id}/save`).then(() => { toast("Saved to Contacts"); setOpen({ ...open, lead_id: "saved" }); mutate(); }).catch((e) => toast((e as Error).message, "error"))} onDelete={() => setOpen(null)} />}

      <Card className="min-w-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-zinc-100 text-left text-xs text-zinc-500">
              <tr>
                <th className="px-4 py-2.5 font-medium">Row</th>
                <th className="px-3 py-2.5 font-medium">Property Address</th>
                <th className="px-3 py-2.5 font-medium">Owner</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-50">
              {data.rows.map((l) => (
                <tr key={l.id}>
                  <td className="px-4 py-2.5 tabular-nums text-zinc-500">{l.row}</td>
                  <td className="px-3 py-2.5 text-zinc-900">
                    {l.address.street}
                    <span className="text-zinc-500">
                      , {l.address.city}, {l.address.state} {l.address.zip}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-zinc-700">{l.deleted ? <span className="text-zinc-400">Deleted</span> : l.owner_name || "—"}</td>
                  <td className="px-3 py-2.5">
                    {l.status === "completed" ? (
                      l.found ? <Badge tone="green">Found · {l.phones} phone{l.phones === 1 ? "" : "s"}</Badge> : <Badge tone="gray">No match</Badge>
                    ) : l.status === "failed" ? (
                      <Badge tone="red">Failed</Badge>
                    ) : (
                      <Badge tone="blue">Waiting</Badge>
                    )}
                    {l.lead_id && <Badge tone="brand" className="ml-1">Saved</Badge>}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {l.found && !l.deleted && (
                      <Button size="sm" variant="ghost" onClick={() => view(l)}>
                        View
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {pages > 1 && (
          <div className="flex items-center justify-between border-t border-zinc-100 px-4 py-2 text-xs text-zinc-500">
            <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span>
              Page {page + 1} of {pages}
            </span>
            <Button size="sm" variant="ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
