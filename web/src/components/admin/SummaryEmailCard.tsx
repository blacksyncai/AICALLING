"use client";

import { Mail } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, Field, Input, Modal, Select, Textarea } from "@/components/ui";
import { fetcher, post } from "@/lib/api";

interface Preview {
  stats: { calls: number; conversations: number; meetings: number; interested: number; callbacks: number; missed_callbacks: number; talk_minutes: number };
  subject: string;
  html: string;
  default_recipients: string[];
}

/** Admin: send this account its calling summary by email, only when you choose to. */
export function SummaryEmailCard({ orgId }: { orgId: string }) {
  const toast = useToast();
  const [period, setPeriod] = useState("7d");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const url = `/api/admin/orgs/${orgId}/summary-email`;
  const { data } = useSWR<Preview>(`${url}?period=${period}&note=${encodeURIComponent(note)}`, fetcher, { keepPreviousData: true });
  const recipients = to.split(/[,\s]+/).map((r) => r.trim()).filter(Boolean);
  const goesTo = recipients.length ? recipients : (data?.default_recipients ?? []);

  async function send() {
    if (!window.confirm(`Send this summary to ${goesTo.join(", ")}?`)) return;
    setBusy(true);
    try {
      const r = await post<{ sent: string[]; failed: string[] }>(url, { period, recipients, note });
      toast(r.failed.length ? `Sent to ${r.sent.length}, failed for ${r.failed.join(", ")}` : `Summary sent to ${r.sent.join(", ")}`, r.failed.length ? "error" : "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const s = data?.stats;
  return (
    <Card className="min-w-0">
      <CardHeader
        title="Send a summary email"
        description="Email this account its calling results. Nothing is sent automatically, only when you click Send."
        action={<Mail className="h-5 w-5 text-zinc-400" />}
      />
      <div className="space-y-3 p-5 text-sm">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Period">
            <Select value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value="today">Today</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
            </Select>
          </Field>
          <Field label="Send to" hint={data ? `Empty = ${data.default_recipients.join(", ") || "no owner email on file"}` : undefined}>
            <Input value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@company.com, another@company.com" />
          </Field>
        </div>
        <Field label="Personal note (optional, shown at the top)">
          <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={600} placeholder="Great week. Three leads below are worth calling today." />
        </Field>
        {s && (
          <p className="rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
            {s.calls} calls · {s.conversations} conversations · {s.meetings} meetings booked · {s.interested} warm leads · {s.callbacks} callbacks
            {s.missed_callbacks ? ` · ${s.missed_callbacks} missed callbacks` : ""} · {s.talk_minutes} min talked
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={!data} onClick={() => setShowPreview(true)}>Preview</Button>
          <Button size="sm" variant="primary" loading={busy} disabled={!data || goesTo.length === 0} onClick={() => void send()}>
            Send summary
          </Button>
        </div>
      </div>
      <Modal open={showPreview} onClose={() => setShowPreview(false)} title={data?.subject ?? "Preview"} wide>
        {data && <iframe title="Summary email preview" sandbox="" srcDoc={data.html} className="h-[70vh] w-full rounded-lg border border-zinc-200" />}
      </Modal>
    </Card>
  );
}
