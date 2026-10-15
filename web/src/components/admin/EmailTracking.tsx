"use client";

import { Activity, Copy, KeyRound } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Input, Spinner } from "@/components/ui";
import { fetcher, put } from "@/lib/api";

export interface Track {
  status: "sent" | "delayed" | "delivered" | "opened" | "clicked" | "bounced" | "complained";
  sent_at: string | null;
  delivered_at: string | null;
  opened_at: string | null;
  open_count: number;
  clicked_at: string | null;
  click_count: number;
  bounced_at: string | null;
  complained_at: string | null;
}
interface Tracking {
  configured: boolean;
  webhook_url: string;
  events: string[];
  last_event_at: string | null;
  last_30_days: { sent: number; delivered: number; opened: number; clicked: number; bounced: number };
}
interface ActivityItem extends Track {
  id: string;
  to: string;
  subject: string;
  kind: string;
}

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";

const LABEL: Record<Track["status"], [string, "gray" | "green" | "blue" | "amber" | "red" | "violet"]> = {
  sent: ["Sent", "gray"],
  delayed: ["Delayed", "amber"],
  delivered: ["Delivered", "blue"],
  opened: ["Opened", "green"],
  clicked: ["Clicked", "violet"],
  bounced: ["Bounced", "red"],
  complained: ["Marked spam", "red"],
};

/** Delivered / Opened / Clicked / Bounced for one sent email. */
export function TrackBadge({ t }: { t?: Track | null }) {
  if (!t) return null;
  const [label, tone] = LABEL[t.status] ?? LABEL.sent;
  const at = t.clicked_at || t.opened_at || t.bounced_at || t.complained_at || t.delivered_at;
  const extra = t.status === "opened" && t.open_count > 1 ? ` ${t.open_count}×` : t.status === "clicked" && t.click_count > 1 ? ` ${t.click_count}×` : "";
  return (
    <span title={at ? `${label} ${when(at)}` : label}>
      <Badge tone={tone}>
        {label}
        {extra}
      </Badge>
    </span>
  );
}

/** Admin → Emails: connect Resend's webhook and see what happened to sent emails. */
export function EmailTrackingCard() {
  const toast = useToast();
  const { data, mutate } = useSWR<Tracking>("/api/admin/emails/tracking", fetcher);
  const { data: act } = useSWR<{ items: ActivityItem[] }>(data?.configured ? "/api/admin/emails/activity?limit=50" : null, fetcher);
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [showActivity, setShowActivity] = useState(false);

  if (!data)
    return (
      <Card className="flex justify-center py-6">
        <Spinner />
      </Card>
    );

  async function save() {
    setSaving(true);
    try {
      await mutate(await put<Tracking>("/api/admin/emails/tracking", { secret: secret.trim() }), false);
      setSecret("");
      setEditing(false);
      toast("Email tracking connected", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  const s = data.last_30_days;
  const pct = (n: number) => (s.delivered ? `${Math.round((n / s.delivered) * 100)}%` : "—");

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Email tracking"
        description="Shows whether people got, opened and clicked the emails we send. Opens are approximate: some mail apps load images automatically."
        action={
          <Badge tone={data.configured ? (data.last_event_at ? "green" : "amber") : "gray"}>
            {data.configured ? (data.last_event_at ? `Last event ${when(data.last_event_at)}` : "Connected · waiting for events") : "Not connected"}
          </Badge>
        }
      />
      <div className="space-y-4 px-5 pb-5">
        {data.configured && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {[
              ["Sent", String(s.sent)],
              ["Delivered", String(s.delivered)],
              ["Opened", `${s.opened} · ${pct(s.opened)}`],
              ["Clicked", `${s.clicked} · ${pct(s.clicked)}`],
              ["Bounced", String(s.bounced)],
            ].map(([k, v]) => (
              <div key={k} className="rounded-xl bg-zinc-50 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-zinc-500">{k} · 30 days</div>
                <div className="text-sm font-semibold text-zinc-900">{v}</div>
              </div>
            ))}
          </div>
        )}

        {(!data.configured || editing) && (
          <div className="space-y-3 rounded-xl bg-zinc-50 p-4 text-sm text-zinc-700">
            <p>
              In Resend, open <strong>Webhooks → Add endpoint</strong>, paste this URL and tick these events:
            </p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-lg bg-white px-3 py-2 text-xs ring-1 ring-zinc-200">{data.webhook_url}</code>
              <Button
                size="sm"
                onClick={() => {
                  void navigator.clipboard.writeText(data.webhook_url);
                  toast("Copied", "success");
                }}
              >
                <Copy className="h-3.5 w-3.5" /> Copy
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {data.events.map((e) => (
                <code key={e} className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-zinc-200">
                  {e}
                </code>
              ))}
            </div>
            <p>Then copy the endpoint&apos;s signing secret (starts with whsec_) and paste it here. It&apos;s stored encrypted.</p>
            <div className="flex gap-2">
              <Input type="password" autoComplete="off" placeholder="whsec_…" value={secret} onChange={(e) => setSecret(e.target.value)} />
              <Button variant="primary" loading={saving} disabled={!secret.trim().startsWith("whsec_")} onClick={() => void save()}>
                <KeyRound className="h-4 w-4" /> Save
              </Button>
            </div>
          </div>
        )}

        {data.configured && (
          <div className="flex flex-wrap gap-4 text-xs">
            <button type="button" className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline" onClick={() => setShowActivity((v) => !v)}>
              <Activity className="h-3.5 w-3.5" /> {showActivity ? "Hide recent emails" : "Recent emails"}
            </button>
            {!editing && (
              <button type="button" className="text-zinc-500 hover:underline" onClick={() => setEditing(true)}>
                Change signing secret
              </button>
            )}
          </div>
        )}

        {showActivity && (
          <div className="max-h-80 divide-y divide-zinc-100 overflow-auto rounded-xl ring-1 ring-zinc-200/80">
            {!act ? (
              <div className="flex justify-center py-6">
                <Spinner />
              </div>
            ) : act.items.length ? (
              act.items.map((m) => (
                <div key={m.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-zinc-900">{m.subject || "(no subject)"}</div>
                    <div className="truncate text-xs text-zinc-500">
                      {m.to} · {m.kind.replace(/_/g, " ")} · {when(m.sent_at)}
                    </div>
                  </div>
                  <TrackBadge t={m} />
                </div>
              ))
            ) : (
              <div className="px-3 py-6 text-center text-sm text-zinc-500">No emails tracked yet.</div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
