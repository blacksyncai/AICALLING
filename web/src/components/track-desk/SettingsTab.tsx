"use client";

import { Copy } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, Field, Input, Notice, Select, Spinner, Toggle } from "@/components/ui";
import { fetcher, patch } from "@/lib/api";
import type { MyPhoneNumbers } from "@/lib/types";
import type { Settings } from "./types";

const ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles",
  "America/Anchorage", "Pacific/Honolulu"];
const hour = (h: number) => new Date(2000, 0, 1, h).toLocaleTimeString(undefined, { hour: "numeric" });

/** Track Desk → Settings: cadence, quiet hours, who gets alerts, the caller number and texting. */
export function SettingsTab() {
  const toast = useToast();
  const { data, mutate } = useSWR<Settings>("/api/track-desk/settings", fetcher);
  const { data: nums } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher);
  const [form, setForm] = useState<Settings | null>(null);
  const [emails, setEmails] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (data) {
      setForm(data);
      setEmails(data.alert_emails.join(", "));
    }
  }, [data]);
  if (!form || !data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setForm({ ...form, [k]: v });

  async function save() {
    if (!form) return;
    setSaving(true);
    try {
      const next = await patch<Settings>("/api/track-desk/settings", {
        broker_name: form.broker_name, agent_name: form.agent_name, caller_number: form.caller_number,
        timezone: form.timezone, check_interval_hours: form.check_interval_hours,
        quiet_start_hour: form.quiet_start_hour, quiet_end_hour: form.quiet_end_hour,
        call_late_loads_in_quiet_hours: form.call_late_loads_in_quiet_hours, sms_only: form.sms_only,
        alert_emails: emails.split(/[,\s]+/).filter(Boolean), alert_phone: form.alert_phone, paused: form.paused,
      });
      await mutate(next, { revalidate: false });
      toast("Settings saved");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Check calls" />
        <div className="space-y-4 p-5">
          <Field label="Company name drivers hear"><Input value={form.broker_name} onChange={(e) => set("broker_name", e.target.value)} /></Field>
          <Field label="Assistant's name" hint={<>The AI introduces itself by this name. <Link className="underline" href={form.agent_id ? `/agents/${form.agent_id}` : "/agents"}>Edit the call script</Link></>}>
            <Input value={form.agent_name} onChange={(e) => set("agent_name", e.target.value)} />
          </Field>
          <Field label="Call from" hint="The number drivers see. Use one number drivers can save.">
            <Select value={form.caller_number} onChange={(e) => set("caller_number", e.target.value)}>
              <option value="">Account default</option>
              {(nums?.numbers ?? []).map((n) => <option key={n.number} value={n.number}>{n.number}{n.label ? ` · ${n.label}` : ""}</option>)}
            </Select>
          </Field>
          <Field label="En-route check every">
            <Select value={String(form.check_interval_hours)} onChange={(e) => set("check_interval_hours", Number(e.target.value))}>
              {[2, 3, 4].map((h) => <option key={h} value={h}>{h} hours</option>)}
            </Select>
          </Field>
          <Field label="Your time zone" hint="Load times in your CSV are read in this zone.">
            <Select value={form.timezone} onChange={(e) => set("timezone", e.target.value)}>
              {[...new Set([form.timezone, ...ZONES])].map((z) => <option key={z} value={z}>{z.replace("America/", "").replace("_", " ")}</option>)}
            </Select>
          </Field>
          <Toggle checked={form.paused} onChange={(v) => set("paused", v)} label="Pause all check calls" description="Nothing is called or texted while paused." />
        </div>
      </Card>

      <Card>
        <CardHeader title="Quiet hours and texting" />
        <div className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3">
            <Field label="No calls from">
              <Select value={String(form.quiet_start_hour)} onChange={(e) => set("quiet_start_hour", Number(e.target.value))}>
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{hour(h)}</option>)}
              </Select>
            </Field>
            <Field label="Until">
              <Select value={String(form.quiet_end_hour)} onChange={(e) => set("quiet_end_hour", Number(e.target.value))}>
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{hour(h)}</option>)}
              </Select>
            </Field>
          </div>
          <p className="-mt-2 text-xs text-zinc-500">In the driver&apos;s local time (where the load is). Quiet hours send a text instead.</p>
          <Toggle checked={form.call_late_loads_in_quiet_hours} onChange={(v) => set("call_late_loads_in_quiet_hours", v)}
                  label="Call late loads in quiet hours" description="Only for loads already marked late." />
          <Toggle checked={form.sms_only} onChange={(v) => set("sms_only", v)} label="Text only" description="Never call drivers; text the three questions instead." />
          {!data.texting_connected ? (
            <Notice tone="amber">
              Texting isn&apos;t connected, so missed calls can&apos;t fall back to a text. Connect your Twilio or Telnyx number in{" "}
              <Link href="/phone-numbers" className="font-medium underline">Phone Numbers</Link>.
            </Notice>
          ) : (
            <Field label="Driver replies webhook" hint="Set this as the incoming-message webhook on your texting number so driver replies are logged.">
              <div className="flex gap-2">
                <Input readOnly value={data.sms_webhook_url} className="font-mono text-xs" />
                <Button onClick={() => { navigator.clipboard.writeText(data.sms_webhook_url); toast("Copied"); }}><Copy className="h-4 w-4" /></Button>
              </div>
            </Field>
          )}
        </div>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader title="Alerts" description="Late and unresponsive loads, and drivers who ask for a person, alert right away. At-risk loads show on the board." />
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          <Field label="Email alerts to" hint="Separate addresses with commas."><Input value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="dispatch@yourco.com" /></Field>
          <Field label="Text alerts to" hint="Needs texting connected."><Input value={form.alert_phone} onChange={(e) => set("alert_phone", e.target.value)} placeholder="(312) 555-0100" /></Field>
        </div>
      </Card>

      <div className="flex items-center gap-3 lg:col-span-2">
        <span className="text-sm text-zinc-500">
          Plan: {data.plans[data.plan]?.label ?? data.plan}{data.plan_limit ? ` · up to ${data.plan_limit} loads a week` : ""}
        </span>
        <Button variant="primary" className="ml-auto" loading={saving} onClick={save}>Save settings</Button>
      </div>
    </div>
  );
}
