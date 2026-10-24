"use client";

import { CalendarCheck, ChevronLeft, ChevronRight, FileUp, PhoneCall, Plug, Plus, Search, Sparkles, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { AddContactModal } from "@/components/contacts/AddContactModal";
import { BulkActionBar } from "@/components/contacts/BulkActionBar";
import { CrmImportModal } from "@/components/contacts/CrmImportModal";
import { ImportContactsModal } from "@/components/contacts/ImportContactsModal";
import { CONTACT_STATUSES, ContactAvatar, DncBadge, StatusPill, TagChip } from "@/components/contacts/shared";
import { Button, Card, EmptyState, Input, Notice, PageHeader, Select, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Campaign, ContactList } from "@/lib/types";
import { canManage, useSession } from "@/lib/session";
import { cn, timeAgo, outcomeLabel } from "@/lib/utils";

const PAGE_SIZE = 50;

/** +15419625730 → (541) 962-5730; anything else as stored. */
function formatPhone(p: string) {
  const d = (p || "").replace(/\D/g, "");
  const n = d.length === 11 && d.startsWith("1") ? d.slice(1) : d;
  return n.length === 10 ? `(${n.slice(0, 3)}) ${n.slice(3, 6)}-${n.slice(6)}` : p;
}

export default function ContactsPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [dnc, setDnc] = useState(false);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [crmOpen, setCrmOpen] = useState(false);
  const [crmKey, setCrmKey] = useState<string | undefined>();
  // /contacts?import=close (from Integrations) opens the CRM importer for that CRM.
  useEffect(() => {
    const k = new URLSearchParams(window.location.search).get("import");
    if (k) {
      setCrmKey(k);
      setCrmOpen(true);
    }
  }, []);
  const { session } = useSession();
  const manager = canManage(session);

  // Deep links like /contacts?status=callback (from the dashboard) open pre-filtered.
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("status");
    if (initial) setStatus(initial);
  }, []);

  // Debounce search input.
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset paging + selection whenever the filters change.
  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [q, status, campaignId, dnc]);

  const url = useMemo(() => {
    const p = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    if (campaignId) p.set("campaign_id", campaignId);
    if (dnc) p.set("dnc", "true");
    return `/api/contacts?${p}`;
  }, [q, status, campaignId, dnc, page]);

  const { data, error, isLoading, mutate } = useSWR<ContactList & { dnc_count?: number }>(url, fetcher, { keepPreviousData: true });
  const { data: campaignsData } = useSWR<{ campaigns: Campaign[] }>("/api/campaigns/", fetcher);
  const campaigns = campaignsData?.campaigns ?? [];

  const items = data?.items ?? [];
  const counts = data?.status_counts ?? {};
  const allTotal = Object.values(counts).reduce((a, b) => a + b, 0);
  const filtered = !!(q || status || campaignId || dnc);
  const dncCount = data?.dnc_count ?? 0;
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const statusChips = useMemo(() => {
    const order = [...CONTACT_STATUSES] as string[];
    return Object.keys(counts)
      .filter((s) => counts[s] > 0)
      .sort((a, b) => (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b)));
  }, [counts]);

  const pageIds = items.map((c) => c.id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const contacted = counts.contacted ?? 0;
  const summary = [
    { label: "Total contacts", value: allTotal, sub: `${(counts.new ?? 0).toLocaleString()} not called yet`, icon: Users, tone: "bg-zinc-900 text-white" },
    { label: "Interested", value: counts.interested ?? 0, sub: contacted ? `of ${contacted.toLocaleString()} reached` : "Wants to hear more", icon: Sparkles, tone: "bg-blue-50 text-blue-600" },
    { label: "Callback", value: counts.callback ?? 0, sub: "Asked us to call back", icon: PhoneCall, tone: "bg-amber-50 text-amber-600" },
    { label: "Meeting booked", value: counts.meeting_booked ?? 0, sub: "On the calendar", icon: CalendarCheck, tone: "bg-emerald-50 text-emerald-600" },
  ];

  const noContactsAtAll = data && allTotal === 0 && !q && !campaignId && !dnc;

  return (
    <>
      <PageHeader
        title="Contacts"
        description="Everyone your agents can call — import lists, organise with tags, and track where each person is in the pipeline."
        action={
          <div className="flex flex-wrap gap-2">
            {manager && (
              <Button onClick={() => setCrmOpen(true)}>
                <Plug className="h-4 w-4" /> Import from CRM
              </Button>
            )}
            <Button onClick={() => setImportOpen(true)}>
              <FileUp className="h-4 w-4" /> Import CSV
            </Button>
            <Button variant="primary" onClick={() => setAddOpen(true)}>
              <Plus className="h-4 w-4" /> Add contact
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4">
          <Notice tone="red">{(error as Error).message}</Notice>
        </div>
      )}

      {!data && !error ? (
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      ) : noContactsAtAll ? (
        <Card>
          <EmptyState
            icon={<Users className="h-5 w-5" />}
            title="No contacts yet"
            description="Import from your CRM or a CSV, or add people one by one. You can then drop them into campaigns or call them directly."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                {manager && (
                  <Button onClick={() => setCrmOpen(true)}>
                    <Plug className="h-4 w-4" /> Import from CRM
                  </Button>
                )}
                <Button onClick={() => setImportOpen(true)}>
                  <FileUp className="h-4 w-4" /> Import CSV
                </Button>
                <Button variant="primary" onClick={() => setAddOpen(true)}>
                  <Plus className="h-4 w-4" /> Add contact
                </Button>
              </div>
            }
          />
        </Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {summary.map((s) => (
              <Card key={s.label} className="rounded-2xl p-4 transition-shadow hover:shadow-md sm:p-5">
                <div className="flex items-center gap-2.5">
                  <span className={cn("flex h-8 w-8 items-center justify-center rounded-full", s.tone)}>
                    <s.icon className="h-4 w-4" />
                  </span>
                  <span className="truncate text-sm font-medium text-zinc-600">{s.label}</span>
                </div>
                <div className="mt-3 font-display text-3xl font-semibold tabular-nums tracking-tight text-zinc-900">{s.value.toLocaleString()}</div>
                <div className="mt-0.5 truncate text-xs text-zinc-400">{s.sub}</div>
              </Card>
            ))}
          </div>

          <Card className="min-w-0 overflow-hidden rounded-2xl">
            {/* Toolbar */}
            <div className="space-y-4 border-b border-zinc-100 bg-white px-4 py-4 sm:px-5 lg:sticky lg:top-0 lg:z-10">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="flex min-w-0 items-center gap-2.5 lg:flex-1">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-zinc-700">
                    <Users className="h-4 w-4" />
                  </span>
                  <h2 className="truncate font-semibold text-zinc-900">{dnc ? "Do-Not-Call" : status ? outcomeLabel(status) : "All contacts"}</h2>
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium tabular-nums text-zinc-500">{total.toLocaleString()}</span>
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <div className="relative min-w-0 sm:w-72">
                    <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                    <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search contacts" className="rounded-full! border-zinc-200 bg-zinc-50 pl-10 focus:bg-white" />
                  </div>
                  <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} className="rounded-full! border-zinc-200 bg-zinc-50 sm:w-52">
                    <option value="">All campaigns</option>
                    {campaigns.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>
              <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5">
                {[["", "All", allTotal] as const, ...statusChips.map((s) => [s, outcomeLabel(s), counts[s]] as const)].map(([value, label, count]) => {
                  const on = status === value && (!!value || !dnc);
                  return (
                    <button
                      key={value || "all"}
                      onClick={() => {
                        setStatus(value);
                        if (!value) setDnc(false);
                      }}
                      className={cn(
                        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                        on ? "bg-zinc-900 text-white shadow-sm" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200/70",
                      )}
                    >
                      {label}
                      <span className={cn("rounded-full px-1.5 tabular-nums", on ? "bg-white/15 text-white" : "bg-white text-zinc-500")}>{count}</span>
                    </button>
                  );
                })}
                {(dncCount > 0 || dnc) && (
                  <button
                    onClick={() => setDnc((v) => !v)}
                    aria-pressed={dnc}
                    className={cn(
                      "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                      dnc ? "bg-red-600 text-white shadow-sm" : "bg-red-50 text-red-700 hover:bg-red-100",
                    )}
                  >
                    Do-Not-Call
                    <span className={cn("rounded-full px-1.5 tabular-nums", dnc ? "bg-white/15 text-white" : "bg-white text-red-500")}>{dncCount}</span>
                  </button>
                )}
              </div>
              {selected.size > 0 && <BulkActionBar ids={[...selected]} campaigns={campaigns} onClear={() => setSelected(new Set())} onDone={() => mutate()} />}
            </div>

            {/* Table */}
            {items.length === 0 ? (
              <div className="px-5 py-12 text-center text-sm text-zinc-500">
                {isLoading ? <Spinner className="mx-auto" /> : filtered ? "No contacts match these filters." : "No contacts on this page."}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-sm">
                  <thead className="text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                    <tr className="border-b border-zinc-100">
                      <th className="w-10 py-3 pl-5 pr-2">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded accent-zinc-900"
                          checked={allOnPage}
                          onChange={() =>
                            setSelected((s) => {
                              const n = new Set(s);
                              pageIds.forEach((id) => (allOnPage ? n.delete(id) : n.add(id)));
                              return n;
                            })
                          }
                          aria-label="Select all on page"
                        />
                      </th>
                      <th className="px-3 py-3">Contact</th>
                      <th className="px-3 py-3">Company</th>
                      <th className="px-3 py-3">Phone</th>
                      <th className="px-3 py-3">Status</th>
                      <th className="px-3 py-3">Campaign</th>
                      <th className="whitespace-nowrap px-3 py-3 pr-5 text-right">Last called</th>
                    </tr>
                  </thead>
                  <tbody className={cn("divide-y divide-zinc-100/80", isLoading && "opacity-60")}>
                    {items.map((c) => (
                      <tr
                        key={c.id}
                        onClick={() => router.push(`/contacts/${c.id}`)}
                        className={cn("group cursor-pointer transition-colors hover:bg-zinc-50/80", selected.has(c.id) && "bg-brand-50/50 hover:bg-brand-50/70")}
                      >
                        <td className="py-3 pl-5 pr-2" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" className="h-4 w-4 rounded accent-zinc-900" checked={selected.has(c.id)} onChange={() => toggle(c.id)} aria-label={`Select ${c.name || c.phone}`} />
                        </td>
                        <td className="max-w-[230px] px-3 py-3">
                          <div className="flex min-w-0 items-center gap-3">
                            <ContactAvatar name={c.name || c.phone} />
                            <div className="min-w-0">
                              <div className="flex min-w-0 items-center gap-1.5">
                                <span className="truncate font-semibold text-zinc-900">{c.name || "Unnamed"}</span>
                                {c.do_not_call && <DncBadge />}
                              </div>
                              <div className="truncate text-xs text-zinc-400">{c.email || `Added ${timeAgo(c.created_at)}`}</div>
                            </div>
                          </div>
                        </td>
                        <td className="max-w-[200px] px-3 py-3">
                          {c.company || c.role ? (
                            <div className="min-w-0">
                              <div className="truncate font-medium text-zinc-700">{c.company || c.role}</div>
                              {c.company && c.role && <div className="truncate text-xs text-zinc-400">{c.role}</div>}
                            </div>
                          ) : (
                            <span className="text-zinc-300">—</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-3 tabular-nums text-zinc-600">{formatPhone(c.phone)}</td>
                        <td className="px-3 py-3">
                          <StatusPill status={c.status} label={outcomeLabel(c.status)} />
                        </td>
                        <td className="max-w-[170px] px-3 py-3">
                          {(c.campaign_name || c.tags.length === 0) && (
                            <div className="truncate text-zinc-600">{c.campaign_name || <span className="text-zinc-300">—</span>}</div>
                          )}
                          {c.tags.length > 0 && (
                            <div className={cn("flex items-center gap-1", c.campaign_name && "mt-1")}>
                              {c.tags.slice(0, 2).map((t) => (
                                <TagChip key={t} tag={t} />
                              ))}
                              {c.tags.length > 2 && <span className="text-[11px] text-zinc-400">+{c.tags.length - 2}</span>}
                            </div>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-3 pr-5 text-right">
                          <span className="text-xs text-zinc-500">{c.last_called_at ? timeAgo(c.last_called_at) : "Never"}</span>
                          <ChevronRight className="ml-1.5 inline h-4 w-4 -translate-x-1 text-zinc-300 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {total > 0 && (
              <div className="flex items-center justify-between gap-3 border-t border-zinc-100 px-5 py-3.5 text-xs text-zinc-500">
                <span>
                  Showing <span className="font-medium text-zinc-800">{from.toLocaleString()}</span>–<span className="font-medium text-zinc-800">{to.toLocaleString()}</span> of{" "}
                  <span className="font-medium text-zinc-800">{total.toLocaleString()}</span>
                </span>
                <div className="flex gap-1.5">
                  <Button size="sm" className="rounded-full!" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} aria-label="Previous page">
                    <ChevronLeft className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">Prev</span>
                  </Button>
                  <Button size="sm" className="rounded-full!" onClick={() => setPage((p) => Math.min(lastPage, p + 1))} disabled={page >= lastPage} aria-label="Next page">
                    <span className="hidden sm:inline">Next</span>
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </>
      )}

      <AddContactModal open={addOpen} onClose={() => setAddOpen(false)} campaigns={campaigns} onCreated={() => mutate()} />
      <CrmImportModal open={crmOpen} onClose={() => setCrmOpen(false)} onDone={() => mutate()} initialKey={crmKey} />
      <ImportContactsModal open={importOpen} onClose={() => setImportOpen(false)} campaigns={campaigns} onDone={() => mutate()} />
    </>
  );
}
