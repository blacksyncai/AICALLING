"use client";

import { ChevronDown, Eye, EyeOff, Pencil, Plus, Send, Trash2, Webhook as WebhookIcon } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import type { Webhook, WebhookEvent } from "@/lib/types";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";
import { ALL_EVENTS, ConfirmModal, CopyButton, EVENT_INFO, Switch } from "./shared";

type TestResult = { ok: boolean; status: number | null; error: string | null; event: string };

export function WebhooksCard({ webhooks, events, onChange }: { webhooks: Webhook[]; events: WebhookEvent[]; onChange: () => void }) {
  const [editing, setEditing] = useState<Webhook | "new" | null>(null);
  const [deleting, setDeleting] = useState<Webhook | null>(null);
  const toast = useToast();
  const available = events.length ? events : ALL_EVENTS;

  return (
    <Card>
      <CardHeader
        title="Webhooks"
        description={
          <>
            We POST a JSON event to your URL when something happens. Verify the{" "}
            <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px] text-zinc-700">X-BlackSync-Signature</code> header (HMAC-SHA256 of the raw body
            with your signing secret).
          </>
        }
        action={
          webhooks.length > 0 && (
            <Button variant="primary" size="sm" onClick={() => setEditing("new")} className="shrink-0">
              <Plus className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Add webhook</span>
              <span className="sm:hidden">Add</span>
            </Button>
          )
        }
      />
      {webhooks.length === 0 ? (
        <EmptyState
          icon={<WebhookIcon className="h-5 w-5" />}
          title="No webhooks yet"
          description="In Zapier, create a Zap with 'Webhooks by Zapier → Catch Hook' and paste its URL here."
          action={
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Plus className="h-4 w-4" />
              Add webhook
            </Button>
          }
        />
      ) : (
        <ul className="divide-y divide-zinc-100">
          {webhooks.map((w) => (
            <WebhookRow key={w.id} webhook={w} onEdit={() => setEditing(w)} onDelete={() => setDeleting(w)} onChange={onChange} />
          ))}
        </ul>
      )}

      <WebhookModal
        key={editing === "new" ? "new" : editing?.id ?? "closed"}
        open={editing !== null}
        webhook={editing === "new" ? null : editing}
        events={available}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          onChange();
        }}
      />
      <ConfirmModal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title="Delete webhook"
        confirmLabel="Delete webhook"
        body={
          <>
            <span className="font-medium text-zinc-900">{deleting?.name}</span> will stop receiving events immediately. This can&apos;t be undone.
          </>
        }
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await del(`/api/integrations/webhooks/${deleting.id}`);
            toast("Webhook deleted");
            setDeleting(null);
            onChange();
          } catch (e) {
            toast((e as Error).message, "error");
          }
        }}
      />
    </Card>
  );
}

function WebhookRow({ webhook: w, onEdit, onDelete, onChange }: { webhook: Webhook; onEdit: () => void; onDelete: () => void; onChange: () => void }) {
  const toast = useToast();
  const [active, setActive] = useState(w.active);
  const [toggling, setToggling] = useState(false);
  const [testing, setTesting] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [showError, setShowError] = useState(false);
  const failed = w.last_status !== null && (w.last_status < 200 || w.last_status >= 300);
  const errored = failed || (w.last_status === null && !!w.last_error);

  const toggle = async (v: boolean) => {
    setActive(v);
    setToggling(true);
    try {
      await patch(`/api/integrations/webhooks/${w.id}`, { active: v });
      toast(v ? "Webhook enabled" : "Webhook paused");
      onChange();
    } catch (e) {
      setActive(!v);
      toast((e as Error).message, "error");
    } finally {
      setToggling(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const r = await post<TestResult>(`/api/integrations/webhooks/${w.id}/test`);
      if (r.ok) toast(`Test ${r.event} delivered — HTTP ${r.status}`);
      else toast(`Test failed${r.status ? ` (HTTP ${r.status})` : ""}: ${r.error ?? "no response"}`, "error");
      onChange();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setTesting(false);
    }
  };

  return (
    <li className="px-5 py-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium text-zinc-900">{w.name || "Untitled webhook"}</span>
            {!active && <Badge tone="gray">Paused</Badge>}
          </div>
          <div className="mt-0.5 truncate font-mono text-xs text-zinc-500" title={w.url}>
            {w.url}
          </div>
        </div>
        <Switch checked={active} onChange={toggle} disabled={toggling} label={`${active ? "Pause" : "Enable"} ${w.name}`} />
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {w.events.map((ev) => (
          <code key={ev} className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[11px] font-medium text-brand-700 ring-1 ring-inset ring-brand-600/15">
            {ev}
          </code>
        ))}
      </div>

      <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div className="min-w-0">
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-zinc-400">Last delivery</div>
          {w.last_status === null && !w.last_error ? (
            <span className="text-zinc-500">Never sent</span>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={errored ? "red" : "green"}>{w.last_status ?? "Error"}</Badge>
              <span className="text-zinc-500" title={formatDateTime(w.last_sent_at)}>
                {timeAgo(w.last_sent_at)}
              </span>
              {errored && w.last_error && (
                <button type="button" onClick={() => setShowError((s) => !s)} className="inline-flex items-center gap-0.5 font-medium text-red-600 hover:text-red-700">
                  {showError ? "Hide error" : "Show error"}
                  <ChevronDown className={cn("h-3 w-3 transition-transform", showError && "rotate-180")} />
                </button>
              )}
            </div>
          )}
          {showError && w.last_error && (
            <div className="mt-2 break-words rounded-md border border-red-100 bg-red-50 px-2 py-1.5 font-mono text-[11px] text-red-800">{w.last_error}</div>
          )}
        </div>
        <div className="min-w-0">
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-zinc-400">Signing secret</div>
          <div className="flex items-center gap-1">
            <code className="min-w-0 flex-1 truncate rounded-md bg-zinc-100 px-2 py-1 font-mono text-[11px] text-zinc-700">
              {reveal ? w.secret : `${w.secret.slice(0, 6)}${"•".repeat(18)}`}
            </code>
            <button
              type="button"
              onClick={() => setReveal((r) => !r)}
              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800"
              aria-label={reveal ? "Hide secret" : "Reveal secret"}
            >
              {reveal ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
            <CopyButton text={w.secret} />
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={test} loading={testing}>
          {!testing && <Send className="h-3.5 w-3.5" />}
          Send test
        </Button>
        <Button size="sm" variant="ghost" onClick={onEdit}>
          <Pencil className="h-3.5 w-3.5" />
          Edit
        </Button>
        <Button size="sm" variant="ghost" onClick={onDelete} className="text-red-600 hover:bg-red-50 hover:text-red-700">
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </Button>
      </div>
    </li>
  );
}

function WebhookModal({
  open,
  webhook,
  events,
  onClose,
  onSaved,
}: {
  open: boolean;
  webhook: Webhook | null;
  events: WebhookEvent[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(webhook?.name ?? "");
  const [url, setUrl] = useState(webhook?.url ?? "");
  const [selected, setSelected] = useState<WebhookEvent[]>(webhook?.events ?? ["call.completed"]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleEvent = (ev: WebhookEvent) => setSelected((s) => (s.includes(ev) ? s.filter((x) => x !== ev) : [...s, ev]));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!/^https?:\/\/\S+$/i.test(url.trim())) return setError("Enter a full URL starting with https:// (or http://).");
    if (selected.length === 0) return setError("Pick at least one event.");
    setSaving(true);
    try {
      const body = { name: name.trim() || "Webhook", url: url.trim(), events: selected };
      if (webhook) await patch(`/api/integrations/webhooks/${webhook.id}`, body);
      else await post("/api/integrations/webhooks", { ...body, active: true });
      toast(webhook ? "Webhook updated" : "Webhook added — send a test to check it");
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={webhook ? "Edit webhook" : "Add webhook"}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Zapier — new meetings" autoFocus />
        </Field>
        <Field label="Endpoint URL" hint="Must be publicly reachable. We send POST requests with a JSON body.">
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://hooks.zapier.com/hooks/catch/…" inputMode="url" className="font-mono text-xs" />
        </Field>
        <div>
          <span className="mb-1.5 block text-xs font-medium text-zinc-700">Events</span>
          <div className="space-y-2">
            {events.map((ev) => {
              const on = selected.includes(ev);
              return (
                <label
                  key={ev}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                    on ? "border-brand-300 bg-brand-50/50" : "border-zinc-200 hover:bg-zinc-50",
                  )}
                >
                  <input type="checkbox" checked={on} onChange={() => toggleEvent(ev)} className="mt-0.5 h-4 w-4 shrink-0 accent-brand-600" />
                  <span className="min-w-0">
                    <code className="block font-mono text-xs font-medium text-zinc-900">{ev}</code>
                    <span className="mt-0.5 block text-xs text-zinc-500">{EVENT_INFO[ev] ?? ""}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </div>
        {error && <Notice tone="red">{error}</Notice>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            {webhook ? "Save changes" : "Add webhook"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
