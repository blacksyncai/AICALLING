"use client";

import { ClipboardPaste, Eye, Search, UserPlus, UserSearch } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import useSWR from "swr";
import { ResultPanel } from "@/components/lead-finder/ResultPanel";
import type { LeadFinderUsage, Lookup, LookupAddress, LookupResponse, ParsedAddress } from "@/components/lead-finder/types";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Field, Input, Notice, Spinner } from "@/components/ui";
import { ApiError, api, del, fetcher, post } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const EMPTY: LookupAddress = { street: "", city: "", state: "", zip: "" };

function resetText(iso: string | undefined, tz: string | undefined) {
  if (!iso) return "";
  const opts: Intl.DateTimeFormatOptions = { weekday: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short" };
  try {
    return new Date(iso).toLocaleString(undefined, { ...opts, timeZone: tz || undefined });
  } catch {
    return new Date(iso).toLocaleString(undefined, opts);
  }
}

function fmtDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}

export default function LeadFinderPage() {
  const toast = useToast();
  const { session } = useSession();
  const tz = session?.org?.timezone ?? undefined;
  const { data: usage, mutate: refreshUsage } = useSWR<LeadFinderUsage>("/api/lead-finder/usage", fetcher);
  const { data: history, mutate: refreshHistory } = useSWR<{ items: Lookup[] }>("/api/lead-finder/lookups", fetcher);

  const [form, setForm] = useState<LookupAddress>(EMPTY);
  const [paste, setPaste] = useState("");
  const [verify, setVerify] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [current, setCurrent] = useState<{ lookup: Lookup; cached: boolean } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  const limitReached = !!usage && usage.remaining <= 0;
  const unavailable = !!usage && (!usage.enabled || !usage.configured);
  const missing = !form.street.trim() || !form.city.trim() || !form.state.trim();

  const set = (k: keyof LookupAddress, v: string) => {
    setForm((f) => ({ ...f, [k]: v }));
    setVerify(false);
  };

  async function splitPasted() {
    if (!paste.trim()) return;
    try {
      const p = await post<ParsedAddress>("/api/lead-finder/parse", { text: paste });
      setForm({ street: p.street, city: p.city, state: p.state, zip: p.zip });
      setVerify(!p.confident);
      setPaste("");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  function show(lookup: Lookup, cached: boolean) {
    setCurrent({ lookup, cached });
    setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || missing) return;
    setBusy(true);
    setError("");
    try {
      const res = await post<LookupResponse>("/api/lead-finder/lookups", form);
      await refreshUsage(res.usage, false);
      refreshHistory();
      show(res.lookup, res.cached);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError((err as Error).message || (status >= 500 ? "Something went wrong. Please try again." : "That lookup didn't work."));
      refreshUsage();
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    setOpening(id);
    try {
      show(await api<Lookup>(`/api/lead-finder/lookups/${id}`), true);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setOpening(null);
    }
  }

  async function save(id: string) {
    setSaving(id);
    try {
      const res = await post<{ lead_id: string; created: boolean }>(`/api/lead-finder/lookups/${id}/save`);
      toast(res.created ? "Saved to Contacts" : "Already in Contacts — updated with these details");
      setCurrent((c) => (c && c.lookup.id === id ? { ...c, lookup: { ...c.lookup, lead_id: res.lead_id } } : c));
      refreshHistory();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(null);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Delete this result's contact details? This can't be undone and doesn't restore a lookup.")) return;
    try {
      await del(`/api/lead-finder/lookups/${id}`);
      setCurrent((c) => (c && c.lookup.id === id ? null : c));
      refreshHistory();
      toast("Result deleted");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  const pct = usage ? Math.min(100, (usage.used / Math.max(1, usage.limit)) * 100) : 0;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold tracking-tight text-zinc-900">Property Owner Lookup</h1>
          <p className="mt-1 text-sm text-zinc-500">Find owner contact information using a property address.</p>
        </div>
        {usage && usage.enabled && (
          <span className={cn("text-sm font-medium tabular-nums", limitReached ? "text-amber-700" : "text-zinc-700")}>
            {usage.remaining} {usage.remaining === 1 ? "lookup" : "lookups"} remaining today
          </span>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
        <Card className="p-5">
          {usage && !usage.enabled ? (
            <Notice tone="amber">Lead Finder isn&apos;t enabled for this account. Contact your BlackSync admin.</Notice>
          ) : (
            <form onSubmit={submit} className="space-y-4" noValidate>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  value={paste}
                  onChange={(e) => setPaste(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void splitPasted();
                    }
                  }}
                  placeholder="Paste a full address, e.g. 1252 E 21st St, Erie, PA 16503"
                  aria-label="Paste a full address"
                  className="min-w-0 flex-1"
                />
                <Button type="button" variant="secondary" onClick={splitPasted} disabled={!paste.trim()}>
                  <ClipboardPaste className="h-4 w-4" /> Fill fields
                </Button>
              </div>

              <div className="grid gap-3 sm:grid-cols-6">
                <Field label="Street Address" className="sm:col-span-6">
                  <Input value={form.street} onChange={(e) => set("street", e.target.value)} placeholder="1252 E 21st St" autoComplete="off" />
                </Field>
                <Field label="City" className="sm:col-span-3">
                  <Input value={form.city} onChange={(e) => set("city", e.target.value)} placeholder="Erie" autoComplete="off" />
                </Field>
                <Field label="State" className="sm:col-span-1">
                  <Input value={form.state} onChange={(e) => set("state", e.target.value)} placeholder="PA" maxLength={20} autoComplete="off" />
                </Field>
                <Field label="ZIP Code" hint="Recommended" className="sm:col-span-2">
                  <Input value={form.zip} onChange={(e) => set("zip", e.target.value)} placeholder="16503" inputMode="numeric" maxLength={10} autoComplete="off" />
                </Field>
              </div>

              {verify && <Notice tone="amber">We weren&apos;t sure how to split that address. Check each field before searching.</Notice>}
              {error && <Notice tone="red">{error}</Notice>}
              {usage && !usage.configured && usage.enabled && (
                <Notice tone="amber">Property lookup is temporarily unavailable. Please try again later.</Notice>
              )}
              {limitReached && (
                <Notice tone="amber">
                  You&apos;ve used your {usage!.limit} property lookups for today. Your allowance resets tomorrow ({resetText(usage!.resets_at, tz)}).
                </Notice>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-zinc-500">Each new address uses one lookup. Opening a saved result is free.</p>
                <Button type="submit" variant="primary" loading={busy} disabled={busy || missing || limitReached || unavailable}>
                  {!busy && <Search className="h-4 w-4" />} {busy ? "Looking up…" : "Find Property Owner"}
                </Button>
              </div>
            </form>
          )}
        </Card>

        <Card className="h-fit p-4">
          <div className="text-xs font-medium text-zinc-500">Daily Lookups</div>
          <div className="mt-1 font-display text-xl font-semibold tabular-nums text-zinc-900">
            {usage ? `${usage.used} / ${usage.limit}` : "—"} <span className="text-sm font-normal text-zinc-500">used</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-100">
            <div className={cn("h-full rounded-full transition-all", limitReached ? "bg-amber-500" : "bg-brand-600")} style={{ width: `${pct}%` }} />
          </div>
          {usage && <p className="mt-2 text-xs text-zinc-500">Resets {resetText(usage.resets_at, tz)}</p>}
        </Card>
      </div>

      <div ref={resultRef} className="mt-4 scroll-mt-4">
        {busy ? (
          <Card className="flex items-center gap-3 p-5 text-sm text-zinc-600">
            <Spinner /> Looking up the property owner…
          </Card>
        ) : (
          current && (
            <ResultPanel
              lookup={current.lookup}
              cached={current.cached}
              saving={saving === current.lookup.id}
              onSave={() => save(current.lookup.id)}
              onDelete={() => remove(current.lookup.id)}
            />
          )
        )}
      </div>

      <h2 className="mb-2 mt-8 text-sm font-semibold text-zinc-900">Recent Lookups</h2>
      <Card className="min-w-0">
        {!history ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : history.items.length === 0 ? (
          <EmptyState icon={<UserSearch className="h-5 w-5" />} title="No lookups yet" description="Search an address above and the result is kept here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-b border-zinc-100 text-left text-xs text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Date</th>
                  <th className="px-3 py-2.5 font-medium">Property Address</th>
                  <th className="px-3 py-2.5 font-medium">Owner Name</th>
                  <th className="px-3 py-2.5 font-medium">Match Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-50">
                {history.items.map((l) => (
                  <tr key={l.id} className={cn(current?.lookup.id === l.id && "bg-brand-50/40")}>
                    <td className="whitespace-nowrap px-4 py-2.5 text-zinc-500">{fmtDate(l.created_at)}</td>
                    <td className="px-3 py-2.5 text-zinc-900">
                      {l.address.street}
                      <span className="text-zinc-500">
                        , {l.address.city}, {l.address.state} {l.address.zip}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-zinc-700">{l.deleted ? <span className="text-zinc-400">Deleted</span> : l.owner_name || "—"}</td>
                    <td className="px-3 py-2.5">
                      {l.found ? <Badge tone="green">Match</Badge> : <Badge tone="gray">No match</Badge>}
                      {l.lead_id && <Badge tone="brand" className="ml-1">Saved</Badge>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right">
                      <div className="inline-flex gap-1">
                        <Button size="sm" variant="ghost" onClick={() => open(l.id)} loading={opening === l.id} disabled={l.deleted}>
                          <Eye className="h-3.5 w-3.5" /> View Result
                        </Button>
                        {l.found && !l.lead_id && !l.deleted && (
                          <Button size="sm" variant="ghost" onClick={() => save(l.id)} loading={saving === l.id}>
                            <UserPlus className="h-3.5 w-3.5" /> Save as Lead
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {usage && <p className="mt-2 text-xs text-zinc-400">Results are kept for {usage.retention_days} days, then their contact details are removed.</p>}
    </div>
  );
}
