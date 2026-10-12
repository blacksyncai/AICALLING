"use client";

import { ClipboardPaste, Eye, FileSpreadsheet, Search, UserPlus, UserSearch } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import useSWR from "swr";
import { BulkLookup } from "@/components/lead-finder/BulkLookup";
import { CreditsCard } from "@/components/lead-finder/CreditsCard";
import { ResultPanel } from "@/components/lead-finder/ResultPanel";
import type { LeadFinderUsage, Lookup, LookupAddress, LookupResponse, ParsedAddress } from "@/components/lead-finder/types";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Field, Input, Notice, Spinner, Tabs } from "@/components/ui";
import { ApiError, api, del, fetcher, post } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const EMPTY: LookupAddress = { street: "", city: "", state: "", zip: "" };

type Mode = "single" | "bulk";

/** A full address: house number, then something that looks like a state and/or ZIP at the end. */
function looksComplete(text: string) {
  const t = text.trim();
  return /^\d/.test(t) && (/\b\d{5}(-?\d{4})?\s*$/.test(t) || (t.includes(",") && /,\s*[^,]+[ ,][A-Za-z]{2}\.?\s*$/.test(t)));
}

function fmtDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}

export default function LeadFinderPage() {
  const toast = useToast();
  const { data: usage, mutate: refreshUsage } = useSWR<LeadFinderUsage>("/api/lead-finder/usage", fetcher);
  const { data: history, mutate: refreshHistory } = useSWR<{ items: Lookup[] }>("/api/lead-finder/lookups", fetcher);

  const { session } = useSession();
  const isAdmin = !!session?.user.is_superadmin;
  const [mode, setMode] = useState<Mode>("single");
  const [form, setForm] = useState<LookupAddress>(EMPTY);
  const [paste, setPaste] = useState("");
  const [verify, setVerify] = useState(false);
  const [priceCheck, setPriceCheck] = useState<{ price: number; balance: number; policy: string } | null>(null);
  const [needsFunds, setNeedsFunds] = useState(false);
  const [filled, setFilled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [current, setCurrent] = useState<{ lookup: Lookup; cached: boolean } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  // Nothing left to pay with: no free lookups today, no prepaid credits, and no usable balance.
  const limitReached =
    !!usage && !usage.unlimited && usage.free_remaining <= 0 && usage.credits <= 0 &&
    (usage.price_cents == null || usage.balance_cents < usage.price_cents);
  const money = (c: number) => `$${(c / 100).toFixed(2)}`;
  const unavailable = !!usage && (!usage.enabled || !usage.configured);
  const missing = !form.street.trim() || !form.city.trim() || !form.state.trim();

  const set = (k: keyof LookupAddress, v: string) => {
    setForm((f) => ({ ...f, [k]: v }));
    setVerify(false);
  };

  /** Split a full address into the four fields (free — never a lookup). Returns whether it filled anything. */
  async function fillFrom(text: string): Promise<boolean> {
    const t = text.trim();
    if (!t) return false;
    try {
      const p = await post<ParsedAddress>("/api/lead-finder/parse", { text: t });
      if (!p.city && !p.state && !p.zip) return false;
      setForm({ street: p.street, city: p.city, state: p.state, zip: p.zip });
      setVerify(!p.confident);
      setPaste("");
      setFilled(true);
      setTimeout(() => setFilled(false), 1800);
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    }
  }

  const splitPasted = () => fillFrom(paste);

  // Typing (not pasting) a full address into the paste box: fill the fields once it looks complete.
  useEffect(() => {
    if (!looksComplete(paste)) return;
    const t = setTimeout(() => void fillFrom(paste), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paste]);

  function show(lookup: Lookup, cached: boolean) {
    setCurrent({ lookup, cached });
    setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  async function submit(e: FormEvent | null, expectedPrice?: number) {
    e?.preventDefault();
    if (busy || missing) return;
    setBusy(true);
    setError("");
    setPriceCheck(null);
    try {
      const body = expectedPrice === undefined ? form : { ...form, expected_price_cents: expectedPrice };
      const res = await post<LookupResponse>("/api/lead-finder/lookups", body);
      await refreshUsage(res.usage, false);
      refreshHistory();
      show(res.lookup, res.cached);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      const code = err instanceof ApiError ? err.body.code : undefined;
      if (code === "confirm_price" && err instanceof ApiError) {
        // Free lookups are used up: show the price and let the user decide.
        setPriceCheck({ price: Number(err.body.price_cents), balance: Number(err.body.balance_cents), policy: String(err.body.policy) });
      } else {
        setError((err as Error).message || (status >= 500 ? "Something went wrong. Please try again." : "That lookup didn't work."));
        if (code === "insufficient_balance") setNeedsFunds(true);
      }
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


  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold tracking-tight text-zinc-900">Property Owner Lookup</h1>
          <p className="mt-1 text-sm text-zinc-500">Find owner contact information using a property address.</p>
        </div>
        {usage && usage.enabled && (
          <span className={cn("text-sm font-medium tabular-nums", limitReached ? "text-amber-700" : "text-zinc-700")}>
            {usage.unlimited
              ? "Unlimited lookups"
              : `${usage.free_remaining} of ${usage.free_daily} free today` +
                (usage.credits ? ` · ${usage.credits.toLocaleString()} prepaid` : "") +
                (usage.price_cents != null ? ` · ${money(usage.balance_cents)} balance` : "")}
          </span>
        )}
      </div>

      {usage?.enabled && !usage.unlimited && (
        <div className="mb-4 grid gap-3 rounded-xl border border-zinc-200 bg-white p-4 text-sm sm:grid-cols-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Price</p>
            <p className="mt-0.5 font-semibold text-zinc-900">8¢–12¢ per lookup</p>
            <p className="text-xs text-zinc-500">12¢ on $5 · 10¢ on $10 · 8¢ on $25 packs</p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Example</p>
            <p className="mt-0.5 font-semibold text-zinc-900">100 addresses ≈ $8–$12</p>
            <p className="text-xs text-zinc-500">Plus {usage.free_daily} free lookups every day</p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">No match, no charge</p>
            <p className="mt-0.5 font-semibold text-emerald-700">Failed addresses are free</p>
            <p className="text-xs text-zinc-500">You only pay when an owner is found</p>
          </div>
        </div>
      )}

      <div className="mb-4 w-full sm:w-72">
        <Tabs<Mode>
          value={mode}
          onChange={setMode}
          tabs={[
            { value: "single", label: "Single address", icon: <Search className="h-3.5 w-3.5" /> },
            { value: "bulk", label: "Bulk CSV", icon: <FileSpreadsheet className="h-3.5 w-3.5" /> },
          ]}
        />
      </div>

      {mode === "bulk" ? (
        <BulkLookup usage={usage} onUsage={() => refreshUsage()} />
      ) : (
      <>
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
                  onPaste={(e) => {
                    const text = e.clipboardData.getData("text");
                    if (!text.trim()) return;
                    e.preventDefault();
                    setPaste(text);
                    void fillFrom(text);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void splitPasted();
                    }
                  }}
                  placeholder="Paste a full address — the fields fill in automatically"
                  aria-label="Paste a full address"
                  className="min-w-0 flex-1"
                />
                <Button type="button" variant="secondary" onClick={splitPasted} disabled={!paste.trim()}>
                  <ClipboardPaste className="h-4 w-4" /> Fill fields
                </Button>
              </div>

              <div className="grid gap-3 sm:grid-cols-6">
                <Field label="Street Address" className="sm:col-span-6">
                  <Input
                    value={form.street}
                    onChange={(e) => set("street", e.target.value)}
                    onPaste={(e) => {
                      // A whole address pasted into Street: split it across the fields instead.
                      const text = e.clipboardData.getData("text");
                      if (!looksComplete(text)) return;
                      e.preventDefault();
                      void fillFrom(text).then((ok) => ok || set("street", text));
                    }}
                    placeholder="1252 E 21st St"
                    autoComplete="off"
                  />
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

              {filled && !verify && <p className="text-xs font-medium text-emerald-700">Address filled in — check it, then search.</p>}
              {verify && <Notice tone="amber">We filled in the fields but weren&apos;t completely sure. Check each one before searching.</Notice>}
              {error && <Notice tone="red">{error}</Notice>}
              {usage && !usage.configured && usage.enabled && (
                <Notice tone="amber">Property lookup is temporarily unavailable. Please try again later.</Notice>
              )}
              {needsFunds && (
                <Notice tone="amber">
                  <Link href="/billing?tab=lookups" className="font-medium underline">
                    Add funds to your lookup balance
                  </Link>{" "}
                  to keep searching today.
                </Notice>
              )}
              {priceCheck && (
                <div className="rounded-lg border border-brand-200 bg-brand-50/60 p-4 text-sm">
                  <p className="font-medium text-zinc-900">You&apos;ve used today&apos;s free lookups.</p>
                  <p className="mt-1 text-zinc-600">
                    This lookup costs <strong>{money(priceCheck.price)}</strong> from your lookup balance ({money(priceCheck.balance)}),{" "}
                    {priceCheck.policy === "completed" ? "charged once the lookup completes." : "charged only if an owner is found."}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {priceCheck.balance >= priceCheck.price ? (
                      <Button type="button" variant="primary" size="sm" onClick={() => void submit(null, priceCheck.price)}>
                        Look up for {money(priceCheck.price)}
                      </Button>
                    ) : (
                      <Link href="/billing?tab=lookups" className="inline-flex h-8 items-center rounded-lg bg-brand-600 px-3 text-xs font-medium text-white hover:bg-brand-700">
                        Add funds
                      </Link>
                    )}
                    <Button type="button" size="sm" variant="ghost" onClick={() => setPriceCheck(null)}>
                      Not now
                    </Button>
                  </div>
                </div>
              )}
              {limitReached && !priceCheck && (
                <Notice tone="amber">
                  {usage?.price_cents != null ? (
                    <>
                      You&apos;ve used today&apos;s free lookups.{" "}
                      <Link href="/billing?tab=lookups" className="font-medium underline">
                        Add funds
                      </Link>{" "}
                      to keep going ({money(usage.price_cents)} per lookup), or come back tomorrow. Saved results stay free to open.
                    </>
                  ) : (
                    "You've used today's free lookups — they reset at midnight UTC. Saved results stay free to open."
                  )}
                </Notice>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-zinc-500">
                  {usage && usage.free_remaining > 0
                    ? `Free — ${usage.free_remaining} free ${usage.free_remaining === 1 ? "lookup" : "lookups"} left today. Saved results are always free to reopen.`
                    : usage?.policy === "completed"
                      ? "Paid lookups are charged once they complete. Saved results are free to reopen."
                      : "Paid lookups are only charged when an owner is found. Saved results are free to reopen."}
                </p>
                <Button type="submit" variant="primary" loading={busy} disabled={busy || missing || limitReached || unavailable}>
                  {!busy && <Search className="h-4 w-4" />} {busy ? "Looking up…" : "Find Property Owner"}
                </Button>
              </div>
            </form>
          )}
        </Card>

        <CreditsCard usage={usage} onChanged={() => refreshUsage()} />
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
      </>
      )}
    </div>
  );
}
