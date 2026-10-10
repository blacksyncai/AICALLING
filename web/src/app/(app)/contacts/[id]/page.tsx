"use client";

import { ArrowLeft, Clock, Mail, Phone, PhoneCall, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import useSWR from "swr";
import { CallNowModal } from "@/components/contacts/CallNowModal";
import { CONTACT_STATUSES, ContactAvatar, TagChip, statusTone } from "@/components/contacts/shared";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Notice, Select, Spinner, Textarea } from "@/components/ui";
import { del, fetcher, patch } from "@/lib/api";
import type { Campaign, Contact, ContactDetail } from "@/lib/types";
import { cn, formatDateTime, formatDuration, humanize, timeAgo } from "@/lib/utils";

type DetailsForm = { name: string; phone: string; email: string; company: string; role: string; campaign_id: string };

const toForm = (c: Contact): DetailsForm => ({
  name: c.name ?? "",
  phone: c.phone ?? "",
  email: c.email ?? "",
  company: c.company ?? "",
  role: c.role ?? "",
  campaign_id: c.campaign_id ?? "",
});

const STATUS_RING: Record<string, string> = {
  green: "border-emerald-200 bg-emerald-50 text-emerald-800",
  blue: "border-blue-200 bg-blue-50 text-blue-800",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
  red: "border-red-200 bg-red-50 text-red-800",
  violet: "border-violet-200 bg-violet-50 text-violet-800",
  brand: "border-brand-200 bg-brand-50 text-brand-800",
  gray: "border-zinc-200 bg-zinc-50 text-zinc-700",
};

export default function ContactDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const toast = useToast();
  const { data: contact, error, mutate } = useSWR<ContactDetail>(`/api/contacts/${id}`, fetcher);
  const { data: campaignsData } = useSWR<{ campaigns: Campaign[] }>("/api/campaigns/", fetcher);
  const campaigns = campaignsData?.campaigns ?? [];

  const [form, setForm] = useState<DetailsForm | null>(null);
  const [notes, setNotes] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [callOpen, setCallOpen] = useState(false);

  // Seed editable state once per contact; later revalidations don't clobber in-progress edits.
  useEffect(() => {
    if (contact && form === null) setForm(toForm(contact));
    if (contact && notes === null) setNotes(contact.notes ?? "");
  }, [contact, form, notes]);

  async function save(key: string, body: Partial<Record<string, unknown>>, success?: string) {
    setBusy(key);
    try {
      const updated = await patch<Contact>(`/api/contacts/${id}`, body);
      await mutate((prev) => (prev ? { ...prev, ...updated, calls: prev.calls } : prev), { revalidate: false });
      if (success) toast(success);
      return updated;
    } catch (e) {
      toast((e as Error).message, "error");
      return null;
    } finally {
      setBusy(null);
    }
  }

  if (error)
    return (
      <>
        <BackLink />
        <Notice tone="red">{(error as Error).message}</Notice>
      </>
    );
  if (!contact || !form)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );

  const displayName = contact.name || contact.phone;
  const detailsDirty = JSON.stringify(form) !== JSON.stringify(toForm(contact));
  const notesDirty = (notes ?? "") !== (contact.notes ?? "");
  const customFields = Object.entries(contact.custom_fields ?? {});
  const set = (k: keyof DetailsForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => (f ? { ...f, [k]: e.target.value } : f));

  async function saveDetails(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    const updated = await save("details", { ...form, campaign_id: form.campaign_id || null }, "Contact saved");
    if (updated) setForm(toForm(updated));
  }

  function addTag() {
    const t = tagInput.trim();
    if (!t) return;
    setTagInput("");
    if (contact!.tags.includes(t)) return;
    save("tags", { tags: [...contact!.tags, t] });
  }

  const statusOptions = (CONTACT_STATUSES as readonly string[]).includes(contact.status) ? CONTACT_STATUSES : [contact.status, ...CONTACT_STATUSES];

  return (
    <>
      <BackLink />

      {/* Header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <ContactAvatar name={displayName} size="lg" />
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold tracking-tight text-zinc-900">{contact.name || "Unnamed contact"}</h1>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-500">
              {(contact.role || contact.company) && <span className="truncate">{[contact.role, contact.company].filter(Boolean).join(" at ")}</span>}
              <span className="inline-flex items-center gap-1 font-mono text-xs">
                <Phone className="h-3 w-3" />
                {contact.phone}
              </span>
              {contact.email && (
                <a href={`mailto:${contact.email}`} className="inline-flex min-w-0 items-center gap-1 truncate text-xs hover:text-zinc-800">
                  <Mail className="h-3 w-3 shrink-0" />
                  <span className="truncate">{contact.email}</span>
                </a>
              )}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Status"
            value={contact.status}
            disabled={busy === "status"}
            onChange={(e) => save("status", { status: e.target.value }, `Status set to ${humanize(e.target.value)}`)}
            className={cn(
              "h-9 rounded-lg border px-3 pr-8 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:opacity-60",
              STATUS_RING[statusTone(contact.status)],
            )}
          >
            {statusOptions.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
          <Button variant="primary" onClick={() => setCallOpen(true)}>
            <PhoneCall className="h-4 w-4" /> Call now
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* Main column */}
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader title="Details" />
            <form onSubmit={saveDetails} className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="Name">
                <Input value={form.name} onChange={set("name")} />
              </Field>
              <Field label="Phone">
                <Input value={form.phone} onChange={set("phone")} required inputMode="tel" className="font-mono" />
              </Field>
              <Field label="Email">
                <Input type="email" value={form.email} onChange={set("email")} />
              </Field>
              <Field label="Company">
                <Input value={form.company} onChange={set("company")} />
              </Field>
              <Field label="Role">
                <Input value={form.role} onChange={set("role")} />
              </Field>
              <Field label="Campaign">
                <Select value={form.campaign_id} onChange={set("campaign_id")}>
                  <option value="">No campaign</option>
                  {/* Keep the current campaign selectable even if the list hasn't loaded */}
                  {contact.campaign_id && !campaigns.some((c) => c.id === contact.campaign_id) && (
                    <option value={contact.campaign_id}>{contact.campaign_name ?? "Current campaign"}</option>
                  )}
                  {campaigns.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="flex items-center justify-end gap-2 sm:col-span-2">
                {detailsDirty && (
                  <Button type="button" variant="ghost" onClick={() => setForm(toForm(contact))}>
                    Discard
                  </Button>
                )}
                <Button variant="primary" loading={busy === "details"} disabled={!detailsDirty}>
                  Save changes
                </Button>
              </div>
            </form>
          </Card>

          <Card>
            <CardHeader title="Notes" description="Private notes for your team." />
            <div className="space-y-3 p-5">
              <Textarea rows={5} value={notes ?? ""} onChange={(e) => setNotes(e.target.value)} placeholder="Add context about this contact…" />
              <div className="flex justify-end">
                <Button
                  variant="primary"
                  size="sm"
                  loading={busy === "notes"}
                  disabled={!notesDirty}
                  onClick={async () => {
                    const updated = await save("notes", { notes: notes ?? "" }, "Notes saved");
                    if (updated) setNotes(updated.notes ?? "");
                  }}
                >
                  Save notes
                </Button>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader title="Activity" description={`${contact.calls.length} call${contact.calls.length === 1 ? "" : "s"}`} />
            {contact.calls.length === 0 ? (
              <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="No calls yet" description="Calls with this contact will show up here with outcomes and summaries." />
            ) : (
              <ol className="relative px-5 py-4">
                {contact.calls.map((call, i) => (
                  <li key={call.id} className="relative pl-7">
                    {i < contact.calls.length - 1 && <span className="absolute left-[7px] top-5 h-full w-px bg-zinc-200" />}
                    <span className="absolute left-0 top-2 flex h-[15px] w-[15px] items-center justify-center rounded-full border-2 border-white bg-brand-500 ring-1 ring-brand-200" />
                    <Link href={`/calls/${call.id}`} className="-mx-2 mb-2 block rounded-lg px-2 py-2 hover:bg-zinc-50">
                      <div className="flex flex-wrap items-center gap-2">
                        <OutcomeBadge outcome={call.outcome} status={call.status} />
                        <span className="text-sm font-medium text-zinc-800">{call.agent_name ?? "Agent"}</span>
                        <span className="inline-flex items-center gap-1 text-xs text-zinc-500">
                          <Clock className="h-3 w-3" />
                          {formatDuration(call.duration_seconds)}
                        </span>
                        <span className="ml-auto text-xs text-zinc-400" title={formatDateTime(call.started_at)}>
                          {timeAgo(call.started_at)}
                        </span>
                      </div>
                      {call.summary && <p className="mt-1.5 line-clamp-3 text-sm leading-relaxed text-zinc-600">{call.summary}</p>}
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        {/* Side column */}
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader title="Tags" />
            <div className="space-y-3 p-5">
              {contact.tags.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {contact.tags.map((t) => (
                    <TagChip key={t} tag={t} onRemove={() => save("tags", { tags: contact.tags.filter((x) => x !== t) })} />
                  ))}
                </div>
              ) : (
                <p className="text-xs text-zinc-500">No tags yet.</p>
              )}
              <Input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTag();
                  }
                }}
                placeholder="Add a tag and press Enter"
                disabled={busy === "tags"}
              />
            </div>
          </Card>

          <Card>
            <CardHeader title="Overview" />
            <dl className="divide-y divide-zinc-100 text-sm">
              {[
                ["Status", <Badge key="s" tone={statusTone(contact.status)}>{humanize(contact.status)}</Badge>],
                [
                  "Campaign",
                  contact.campaign_id ? (
                    <Link key="c" href={`/campaigns/${contact.campaign_id}`} className="truncate font-medium text-brand-700 hover:underline">
                      {contact.campaign_name ?? "View campaign"}
                    </Link>
                  ) : (
                    "—"
                  ),
                ],
                ["Last called", contact.last_called_at ? timeAgo(contact.last_called_at) : "Never"],
                ["Source", humanize(contact.source)],
                ["Added", formatDateTime(contact.created_at)],
              ].map(([label, value]) => (
                <div key={label as string} className="flex items-center justify-between gap-4 px-5 py-2.5">
                  <dt className="text-xs text-zinc-500">{label}</dt>
                  <dd className="min-w-0 truncate text-right text-zinc-800">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>

          {customFields.length > 0 && (
            <Card>
              <CardHeader title="Custom fields" description="Use these in agent prompts as {{field}}." />
              <dl className="divide-y divide-zinc-100 text-sm">
                {customFields.map(([k, v]) => (
                  <div key={k} className="flex items-start justify-between gap-4 px-5 py-2.5">
                    <dt className="shrink-0 font-mono text-xs text-zinc-500">{k}</dt>
                    <dd className="min-w-0 break-words text-right text-zinc-800">{v || "—"}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}

          <Card className="border-red-200">
            <CardHeader title="Danger zone" />
            <div className="flex flex-wrap items-center justify-between gap-3 p-5">
              <p className="text-xs text-zinc-500">Delete this contact. Call history is kept.</p>
              <Button
                variant="danger"
                size="sm"
                loading={busy === "delete"}
                onClick={async () => {
                  if (!confirm(`Delete ${displayName}? Their call history is kept.`)) return;
                  setBusy("delete");
                  try {
                    await del(`/api/contacts/${id}`);
                    toast("Contact deleted");
                    router.push("/contacts");
                  } catch (e) {
                    toast((e as Error).message, "error");
                    setBusy(null);
                  }
                }}
              >
                <Trash2 className="h-3.5 w-3.5" /> Delete contact
              </Button>
            </div>
          </Card>
        </div>
      </div>

      <CallNowModal open={callOpen} onClose={() => setCallOpen(false)} contactId={id} contactName={displayName} phone={contact.phone} onCalled={() => mutate()} />
    </>
  );
}

function BackLink() {
  return (
    <Link href="/contacts" className="mb-4 inline-flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-800">
      <ArrowLeft className="h-3 w-3" /> Contacts
    </Link>
  );
}
