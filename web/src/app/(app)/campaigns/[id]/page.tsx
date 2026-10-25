"use client";

import { ArrowLeft, FileUp, Pause, Phone, Play, Plus, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import MatteAlertFeedback from "@/components/ui/matte-alert-feedback";
import { InboundCampaign } from "@/components/campaigns/InboundCampaign";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { CallingRulesCard, CallingStatus } from "@/components/campaigns/CallingRules";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice, Select, Spinner, Textarea } from "@/components/ui";
import { del, fetcher, patch, post } from "@/lib/api";
import type { Agent, Call, Campaign, Lead, SettingsStatus } from "@/lib/types";
import { CAMPAIGN_TONE, OUTCOME_TONE, formatDuration, humanize, timeAgo, outcomeLabel } from "@/lib/utils";

type CampaignLead = Lead & { do_not_call?: boolean; attempts?: number; next_attempt_at?: string | null; fields_pending?: boolean; voicemails?: number; verified?: boolean; wrong_number?: boolean };

const SAMPLE_CSV = `name,phone,company,email,city
Jane Cooper,+14155550123,Acme Inc,jane@acme.com,San Francisco
Marcus Lee,+14155550188,Globex,marcus@globex.com,Austin`;

/** Reads a dropped file if it's a CSV; returns null for anything else. */
async function readDroppedCsv(e: React.DragEvent): Promise<string | null> {
  const f = e.dataTransfer.files?.[0];
  if (!f) return null;
  if (!/\.(csv|txt)$/i.test(f.name) && !/csv|text\/plain/.test(f.type)) return null;
  return f.text();
}

const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer.types || []).includes("Files");

function ImportModal({ open, onClose, campaignId, onDone, initialCsv }: { open: boolean; onClose: () => void; campaignId: string; onDone: () => void; initialCsv?: string }) {
  const toast = useToast();
  const [csv, setCsv] = useState("");
  const [over, setOver] = useState(false);
  useEffect(() => {
    if (open && initialCsv) setCsv(initialCsv);
  }, [open, initialCsv]);
  const [busy, setBusy] = useState(false);
  const rows = csv.trim() ? csv.trim().split(/\r?\n/).length - 1 : 0;

  async function submit() {
    setBusy(true);
    try {
      const res = await post<{ created: number; skipped: number }>(`/api/campaigns/${campaignId}/leads/import`, { csv });
      toast(`Imported ${res.created} contact${res.created === 1 ? "" : "s"}${res.skipped ? ` · skipped ${res.skipped} without a valid phone` : ""}`);
      setCsv("");
      onDone();
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Import contacts" wide>
      <div className="space-y-4">
        <Notice tone="blue">
          CSV with a header row. A <b>phone</b> column is required; <b>name</b>, <b>company</b>, <b>email</b>, <b>role</b> are recognised automatically, and every other
          column becomes a variable you can use in the prompt — e.g. <code>{"{{city}}"}</code>. 10-digit numbers are assumed to be US/Canada (+1).
        </Notice>
        <div className="flex flex-wrap gap-2">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium hover:bg-zinc-50">
            <FileUp className="h-3.5 w-3.5" /> Choose CSV file
            <input
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setCsv(await f.text());
                e.target.value = "";
              }}
            />
          </label>
          <Button size="sm" variant="ghost" onClick={() => setCsv(SAMPLE_CSV)}>
            Use sample
          </Button>
        </div>
        <div
          className={`relative rounded-lg ${over ? "ring-2 ring-brand-500 ring-offset-2" : ""}`}
          onDragOver={(e) => {
            if (!hasFiles(e)) return;
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={async (e) => {
            if (!hasFiles(e)) return;
            e.preventDefault();
            setOver(false);
            const text = await readDroppedCsv(e);
            if (text == null) toast("Drop a .csv file", "error");
            else setCsv(text);
          }}
        >
          <Textarea rows={10} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder={`Drop a CSV here, paste it, or choose a file\n\n${SAMPLE_CSV}`} className="font-mono text-xs" />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-zinc-500">{rows > 0 ? `${rows} row${rows === 1 ? "" : "s"}` : "Paste CSV or choose a file"}</span>
          <Button variant="primary" onClick={submit} loading={busy} disabled={rows < 1}>
            Import {rows > 0 ? rows : ""} {rows === 1 ? "contact" : "contacts"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function AddLeadModal({ open, onClose, campaignId, onDone }: { open: boolean; onClose: () => void; campaignId: string; onDone: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ name: "", phone: "", company: "", email: "" });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const header = "name,phone,company,email";
      const esc = (v: string) => `"${v.replace(/"/g, '""')}"`;
      const res = await post<{ created: number }>(`/api/campaigns/${campaignId}/leads/import`, {
        csv: `${header}\n${[form.name, form.phone, form.company, form.email].map(esc).join(",")}`,
      });
      if (!res.created) throw new Error("That phone number doesn't look valid — include the country code, e.g. +14155550123");
      setForm({ name: "", phone: "", company: "", email: "" });
      onDone();
      onClose();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Add a contact">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <Input value={form.name} onChange={set("name")} required autoFocus />
        </Field>
        <Field label="Phone">
          <Input value={form.phone} onChange={set("phone")} placeholder="+14155550123" required />
        </Field>
        <Field label="Company">
          <Input value={form.company} onChange={set("company")} />
        </Field>
        <Field label="Email">
          <Input type="email" value={form.email} onChange={set("email")} />
        </Field>
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy}>
            Add contact
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function CampaignDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const toast = useToast();
  // Poll fast only while it's dialing; a draft, paused or finished campaign barely changes.
  const { data: campaign, mutate: refreshCampaign, error } = useSWR<Campaign>(`/api/campaigns/${id}`, fetcher, {
    refreshInterval: (c) => (c?.status === "running" ? 5000 : 30000),
  });
  const live = campaign?.status === "running";
  const { data: leadsData, mutate: refreshLeads } = useSWR<{ leads: CampaignLead[]; total?: number; status_counts?: Record<string, number> }>(
    campaign && campaign.direction === "inbound" ? null : `/api/campaigns/${id}/leads?page_size=200`,
    fetcher,
    { refreshInterval: live ? 5000 : 0 },
  );
  // Contacts added from a CRM before their fields were pulled: fetch them once so they show like CSV columns.
  const [fieldsAsked, setFieldsAsked] = useState(false);
  useEffect(() => {
    if (fieldsAsked || !leadsData?.leads.some((l) => l.fields_pending)) return;
    setFieldsAsked(true);
    post(`/api/campaigns/${id}/crm-fields`, {}).then(() => refreshLeads()).catch(() => {});
  }, [fieldsAsked, leadsData, id, refreshLeads]);
  const { data: calls } = useSWR<{ items: Call[] }>(`/api/calls/?campaign_id=${id}&page_size=50`, fetcher, { refreshInterval: live ? 5000 : 30000 });
  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const { data: status } = useSWR<SettingsStatus>("/api/settings/status", fetcher);
  const [importOpen, setImportOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [droppedCsv, setDroppedCsv] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rulesDirty, setRulesDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const leads = useMemo(() => leadsData?.leads ?? [], [leadsData]);
  const refresh = () => {
    refreshCampaign();
    refreshLeads();
  };

  async function action(name: string, fn: () => Promise<unknown>, success?: string): Promise<boolean> {
    setBusy(name);
    try {
      await fn();
      if (success) toast(success);
      if (name !== "delete") refresh();
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    } finally {
      setBusy(null);
    }
  }

  if (error) return <Notice tone="red">{error.message}</Notice>;
  if (!campaign)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );

  if ((campaign.direction ?? "outbound") === "inbound") {
    return <InboundCampaign campaign={campaign} calls={calls?.items ?? []} agents={agents ?? []} onChange={() => void refreshCampaign()} />;
  }

  const counts =
    leadsData?.status_counts ??
    leads.reduce<Record<string, number>>((acc, l) => (l.do_not_call ? acc : ((acc[l.status] = (acc[l.status] ?? 0) + 1), acc)), {});
  const totalLeads = leadsData?.total ?? leads.length;
  const pending = (counts.new ?? 0) + (campaign.pending_retries ?? 0);
  const running = campaign.status === "running";
  const allSelected = leads.length > 0 && selected.size === leads.length;
  const canDial = !!status?.capabilities.phone_call;

  return (
    <>
      <Link href="/campaigns" className="mb-4 inline-flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-3 w-3" /> Campaigns
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{campaign.name}</h1>
            <Badge tone={CAMPAIGN_TONE[campaign.status]}>{campaign.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-zinc-500">Created {timeAgo(campaign.created_at)}</p>
          {["draft", "running", "paused"].includes(campaign.status) && (
            <div className="mt-1">
              <CallingStatus campaign={campaign} />
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {running ? (
            <Button onClick={() => action("pause", () => post(`/api/campaigns/${id}/pause`), "Campaign paused")} loading={busy === "pause"}>
              <Pause className="h-4 w-4" /> Pause
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => action("start", () => post(`/api/campaigns/${id}/start`), "Campaign started — follows saved calling hours")}
              loading={busy === "start"}
              disabled={rulesDirty || !canDial || pending === 0 || !["draft", "paused"].includes(campaign.status)}
              title={rulesDirty ? "Save calling rules first" : !canDial ? "Phone calling isn't available yet" : pending === 0 ? "No contacts left to call" : undefined}
            >
              <Play className="h-4 w-4" /> {campaign.status === "paused" ? "Resume" : "Start campaign"}
            </Button>
          )}
          <Button
            variant="ghost"
            aria-label="Delete campaign"
            onClick={() => {
              if (confirm("Delete this campaign and its contacts? Call logs are kept.")) action("delete", () => del(`/api/campaigns/${id}`)).then((ok) => ok && router.push("/campaigns"));
            }}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {!canDial && status && (
        <div className="mb-6">
          <Notice>
            Phone calling isn&apos;t switched on for your account yet, so this campaign can&apos;t dial. You can still build
            the list now — message us in the chat and we&apos;ll get it set up.
          </Notice>
        </div>
      )}

      {campaign.status === "paused" && campaign.pause_reason === "plan" && (
        <div className="mb-6 max-w-2xl">
          <Notice tone="amber">
            This campaign paused because its agent is over your plan&apos;s active-agent limit. Pause an agent you don&apos;t need, add an agent slot or upgrade, then press Resume.{" "}
            <Link href="/billing?tab=plans#agent-slots" className="font-medium underline">
              Plans &amp; agent slots
            </Link>
          </Notice>
        </div>
      )}

      {campaign.status === "paused" && campaign.pause_reason === "number_released" && (
        <div className="mb-6 max-w-2xl"><Notice tone="amber">
          A phone number used by this campaign was released. Choose active caller numbers in Calling rules before resuming.
        </Notice></div>
      )}

      {campaign.status === "paused" && campaign.pause_reason === "setup" && (
        <div className="mb-6 max-w-2xl">
          <Notice tone="amber">
            This campaign paused because calls couldn&apos;t be placed for a moment. Nothing is lost — press Resume to pick up
            where it left off. If it pauses again, message us in the chat.
          </Notice>
        </div>
      )}

      {campaign.status === "paused" && campaign.pause_reason === "credits" && (
        <div className="mb-6 max-w-2xl">
          <MatteAlertFeedback
            cardTitle="Campaign paused"
            pillText="Out of credits"
            cardDescription="This campaign stopped dialing because your calling credits ran out. Nothing is lost — it picks up where it left off."
            alertTitle="Add credits, then press Resume"
            alertDetail="Turn on auto-recharge so campaigns never stop mid-list."
            showControls={false}
            action={
              <Link href="/billing?tab=credits" className="inline-flex h-8 items-center rounded-lg bg-brand-600 px-3 text-xs font-medium text-white hover:bg-brand-700">
                Buy credits
              </Link>
            }
          />
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        {[
          ["Contacts", campaign.total_targets],
          ["To call", counts.new ?? 0],
          ["Dialed", campaign.total_dialed],
          ["Qualified", campaign.total_qualified],
          ["Booked", campaign.total_booked],
        ].map(([label, value]) => (
          <Card key={label} className="p-4">
            <div className="text-xs text-zinc-500">{label}</div>
            <div className="mt-1 text-xl font-semibold">{value}</div>
          </Card>
        ))}
      </div>

      <Card className="mb-6">
        <CardHeader title="Settings" description={running ? "Pause the campaign to change these." : undefined} />
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          <Field label="Agent">
            <Select
              value={campaign.agent_id ?? ""}
              disabled={running}
              onChange={(e) => action("agent", () => patch(`/api/campaigns/${id}`, { agent_id: e.target.value }), "Agent updated")}
            >
              {!campaign.agent_id && <option value="">Pick an agent…</option>}
              {agents?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Simultaneous calls" hint="How many calls can be live at once. More finishes the list faster; your plan may cap this.">
            <Select
              value={campaign.max_concurrent_calls}
              disabled={running}
              onChange={(e) => action("conc", () => patch(`/api/campaigns/${id}`, { max_concurrent_calls: Number(e.target.value) }), "Updated")}
            >
              {[1, 2, 3, 5, 10].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Card>

      <CallingRulesCard campaign={campaign} onSaved={refreshCampaign} onDirtyChange={setRulesDirty} />

      <Card
        className="relative mb-6"
        onDragOver={(e: React.DragEvent) => {
          if (!hasFiles(e) || importOpen) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(e: React.DragEvent) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={async (e: React.DragEvent) => {
          if (!hasFiles(e) || importOpen) return;
          e.preventDefault();
          setDragging(false);
          const text = await readDroppedCsv(e);
          if (text == null) return toast("Drop a .csv file", "error");
          setDroppedCsv(text);
          setImportOpen(true);
        }}
      >
        {dragging && (
          <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-[inherit] border-2 border-dashed border-brand-500 bg-brand-50/90 text-brand-700">
            <FileUp className="h-6 w-6" />
            <span className="text-sm font-semibold">Drop your CSV to import contacts</span>
          </div>
        )}
        <CardHeader
          title={`Contacts (${totalLeads.toLocaleString()})`}
          description={totalLeads > leads.length ? `Showing the newest ${leads.length} — every contact is still called.` : undefined}
          action={
            <div className="flex flex-wrap gap-2">
              {selected.size > 0 && (
                <Button
                  size="sm"
                  variant="primary"
                  loading={busy === "call"}
                  disabled={rulesDirty || !canDial}
                  title={rulesDirty ? "Save calling rules first" : undefined}
                  onClick={() =>
                    action(
                      "call",
                      () =>
                        post<{ dispatched: number; skipped_dnc?: number }>(`/api/campaigns/${id}/call`, { lead_ids: [...selected] }).then((r) => {
                          setSelected(new Set());
                          toast(
                            `Calling ${r.dispatched} contact${r.dispatched === 1 ? "" : "s"}` +
                              (r.skipped_dnc ? ` · skipped ${r.skipped_dnc} on the Do-Not-Call list` : ""),
                          );
                        }),
                    )
                  }
                >
                  <Phone className="h-3.5 w-3.5" /> Call {selected.size} selected
                </Button>
              )}
              <Button size="sm" onClick={() => setAddOpen(true)}>
                <Plus className="h-3.5 w-3.5" /> Add
              </Button>
              <Button size="sm" onClick={() => setImportOpen(true)}>
                <FileUp className="h-3.5 w-3.5" /> Import CSV
              </Button>
            </div>
          }
        />
        {leads.length === 0 ? (
          <EmptyState
            icon={<Users className="h-5 w-5" />}
            title="No contacts yet"
            description="Drag a CSV here, import one, or add contacts one by one."
            action={
              <Button variant="primary" onClick={() => setImportOpen(true)}>
                <FileUp className="h-4 w-4" /> Import CSV
              </Button>
            }
          />
        ) : (
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 border-b border-zinc-100 bg-white text-left text-xs text-zinc-500">
                <tr>
                  <th className="w-10 px-5 py-3">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(leads.map((l) => l.id)))}
                      aria-label="Select all"
                    />
                  </th>
                  <th className="px-3 py-3 font-medium">Name</th>
                  <th className="px-3 py-3 font-medium">Phone</th>
                  <th className="px-3 py-3 font-medium">Company</th>
                  <th className="px-3 py-3 font-medium">Extra fields</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {leads.map((l) => (
                  <tr key={l.id} className="hover:bg-zinc-50">
                    <td className="px-5 py-2.5">
                      <input
                        type="checkbox"
                        checked={selected.has(l.id)}
                        onChange={() =>
                          setSelected((s) => {
                            const n = new Set(s);
                            if (n.has(l.id)) n.delete(l.id);
                            else n.add(l.id);
                            return n;
                          })
                        }
                        aria-label={`Select ${l.name}`}
                      />
                    </td>
                    <td className="px-3 py-2.5 font-medium">
                      <span className="flex items-center gap-2">
                        {l.name}
                        {l.do_not_call && (
                          <Badge tone="red" className="shrink-0">
                            DNC
                          </Badge>
                        )}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-zinc-600">{l.phone}</td>
                    <td className="px-3 py-2.5 text-zinc-600">{l.company || "—"}</td>
                    <td className="max-w-[220px] truncate px-3 py-2.5 text-xs text-zinc-500">
                      {Object.entries(l.custom_fields ?? {})
                        .map(([k, v]) => `${humanize(k)}: ${v}`)
                        .join(" · ") || "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={l.status === "new" ? "gray" : l.status === "calling" ? "brand" : (OUTCOME_TONE[l.status] ?? "gray")}>{outcomeLabel(l.status)}</Badge>
                      {(l.attempts ?? 0) > 1 && <span className="ml-1.5 text-xs text-zinc-400">{l.attempts} tries</span>}
                      <span className="mt-1 flex flex-wrap gap-1">
                        {l.verified && <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium leading-none text-emerald-700">Verified</span>}
                        {l.wrong_number && <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium leading-none text-red-700">Wrong number</span>}
                        {(l.voicemails ?? 0) > 0 && (
                          <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium leading-none text-violet-700">
                            Voicemail{(l.voicemails ?? 0) > 1 ? ` ×${l.voicemails}` : ""}
                          </span>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Calls in this campaign" />
        {!calls?.items.length ? (
          <p className="px-5 py-6 text-sm text-zinc-500">No calls yet.</p>
        ) : (
          <div className="divide-y divide-zinc-100">
            {calls.items.map((c) => (
              <Link key={c.id} href={`/calls/${c.id}`} className="flex items-center gap-4 px-5 py-3 hover:bg-zinc-50">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{c.contact_name ?? c.to_phone}</div>
                  <div className="truncate text-xs text-zinc-500">{c.summary ?? c.to_phone}</div>
                </div>
                <OutcomeBadge outcome={c.outcome} status={c.status} />
                <span className="w-12 text-right text-xs text-zinc-500">{formatDuration(c.duration_seconds)}</span>
                <span className="w-16 text-right text-xs text-zinc-400">{timeAgo(c.started_at)}</span>
              </Link>
            ))}
          </div>
        )}
      </Card>

      <ImportModal
        open={importOpen}
        onClose={() => {
          setImportOpen(false);
          setDroppedCsv("");
        }}
        campaignId={id}
        onDone={refresh}
        initialCsv={droppedCsv}
      />
      <AddLeadModal open={addOpen} onClose={() => setAddOpen(false)} campaignId={id} onDone={refresh} />
    </>
  );
}
