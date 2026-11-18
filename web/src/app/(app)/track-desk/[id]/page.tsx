"use client";

import { ArrowLeft, CheckCircle2, MapPin, MessageSquare, Phone, PhoneCall, RefreshCw, StickyNote, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { RecordingPlayer } from "@/components/calls/RecordingPlayer";
import { useToast } from "@/components/toast";
import {
  ALERT_LABEL, CHECK_KIND, OUTCOME, STATUS, etaText, when, windowText, type Check, type LoadDetail,
} from "@/components/track-desk/types";
import { Badge, Button, Card, CardHeader, Field, Input, Modal, Select, Spinner, Toggle } from "@/components/ui";
import { fetcher, patch, post } from "@/lib/api";
import { cn, formatPhone, timeAgo } from "@/lib/utils";

export default function LoadPage() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { data, mutate, error } = useSWR<LoadDetail>(`/api/track-desk/loads/${id}`, fetcher, { refreshInterval: 15000 });
  const [busy, setBusy] = useState<string | null>(null);
  const [manual, setManual] = useState(false);

  if (error) return <Card className="p-8 text-sm text-zinc-600">{error.message}</Card>;
  if (!data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const l = data.load;
  const s = STATUS[l.status];
  const closed = l.status === "delivered" || l.status === "cancelled";

  async function act(path: string, label: string) {
    setBusy(path);
    try {
      await post(`/api/track-desk/loads/${id}/${path}`);
      await mutate();
      toast(label);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <Link href="/track-desk" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-4 w-4" /> Board
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-[26px] font-semibold tracking-tight text-zinc-900">Load {l.load_id}</h1>
            <Badge tone={s.tone}><span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />{s.label}</Badge>
            {l.round && <Badge tone="blue">Checking now</Badge>}
            {l.do_not_call && <Badge>Driver opted out</Badge>}
          </div>
          <p className="mt-1 text-sm text-zinc-500">
            {l.pickup.city}, {l.pickup.state} → {l.delivery.city}, {l.delivery.state}
            {l.shipper_name ? ` · ${l.shipper_name}` : ""}{l.broker_reference ? ` · Ref ${l.broker_reference}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href={`tel:${l.driver_phone}`}><Button variant="primary"><Phone className="h-4 w-4" /> Call driver</Button></a>
          {!closed && (
            <>
              <Button loading={busy === "check-now"} disabled={!!l.round || l.do_not_call} onClick={() => act("check-now", "Checking in with the driver")}>
                <RefreshCw className="h-4 w-4" /> Check now
              </Button>
              <Button onClick={() => setManual(true)}><StickyNote className="h-4 w-4" /> Add check-in</Button>
              <Button loading={busy === "mark-delivered"} onClick={() => act("mark-delivered", "Marked delivered")}><CheckCircle2 className="h-4 w-4" /> Delivered</Button>
              <Button variant="ghost" loading={busy === "mark-cancelled"} onClick={() => act("mark-cancelled", "Load cancelled")}><XCircle className="h-4 w-4" /> Cancel</Button>
            </>
          )}
          {closed && <Button loading={busy === "reopen"} onClick={() => act("reopen", "Load reopened")}>Reopen</Button>}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <div className="space-y-5">
          <Card>
            <div className="grid gap-4 p-5 sm:grid-cols-3">
              <Info label="Last location" value={l.last_location || "No check-in yet"} icon={<MapPin className="h-3.5 w-3.5" />} />
              <Info label="ETA" value={etaText(l)} />
              <Info label="Loaded" value={{ yes: "Loaded, rolling", no: "Not loaded yet", unknown: "—" }[l.loaded]} />
              <Info label="Pickup window" value={windowText(l.pickup)} />
              <Info label="Delivery window" value={windowText(l.delivery)} />
              <Info label="Next check" value={l.next_check_at ? `${CHECK_KIND[l.next_check_kind] ?? "Check"} · ${when(l.next_check_at)}` : closed ? "None (load closed)" : "None"} />
              {l.delay_reason && <div className="sm:col-span-3"><Info label="Delay" value={l.delay_reason} /></div>}
            </div>
          </Card>

          <Card>
            <CardHeader title="Timeline" description="Every call, text and check-in on this load." />
            {data.timeline.length === 0 ? (
              <p className="p-5 text-sm text-zinc-500">Nothing yet. The first check is {l.next_check_at ? when(l.next_check_at) : "not scheduled"}.</p>
            ) : (
              <ol className="divide-y divide-zinc-100">
                {data.timeline.map((c) => <TimelineItem key={c.id} c={c} />)}
              </ol>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <DriverCard detail={data} onSaved={() => mutate()} />
          {data.alerts.length > 0 && (
            <Card>
              <CardHeader title="Alerts" />
              <div className="divide-y divide-zinc-100">
                {data.alerts.map((a) => (
                  <div key={a.id} className="p-4 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge tone={a.kind === "late" || a.kind === "unresponsive" ? "red" : "amber"}>{ALERT_LABEL[a.kind] ?? a.kind}</Badge>
                      <span className="text-xs text-zinc-500">{timeAgo(a.sent_at)}</span>
                    </div>
                    <p className="mt-1 whitespace-pre-line text-zinc-600">{a.message}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
      <ManualCheckIn open={manual} onClose={() => setManual(false)} loadId={id} onSaved={() => mutate()} />
    </div>
  );
}

function Info({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium text-zinc-500">{label}</div>
      <div className="mt-0.5 inline-flex items-center gap-1 text-sm font-medium text-zinc-900">{icon}{value}</div>
    </div>
  );
}

function TimelineItem({ c }: { c: Check }) {
  const [open, setOpen] = useState(false);
  const Icon = c.channel === "call" ? PhoneCall : c.channel === "sms" ? MessageSquare : StickyNote;
  const got = c.location || c.eta || c.eta_text || c.loaded !== "unknown";
  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Icon className="h-4 w-4 text-zinc-400" />
        <span className="font-medium text-zinc-900">{CHECK_KIND[c.kind] ?? c.kind}</span>
        <Badge tone={c.outcome === "answered" || c.outcome === "sms_reply" || c.outcome === "manual" ? "green" : c.outcome === "dialing" ? "blue" : "gray"}>
          {OUTCOME[c.outcome] ?? c.outcome}
        </Badge>
        {c.needs_review && <Badge tone="amber">Check this answer</Badge>}
        <span className="ml-auto text-xs text-zinc-500">{when(c.attempted_at)}{c.duration_sec ? ` · ${c.duration_sec}s` : ""}</span>
      </div>
      {got && (
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 pl-6 text-sm text-zinc-700">
          {c.location && <span>📍 {c.location}</span>}
          {c.loaded !== "unknown" && <span>{c.loaded === "yes" ? "Loaded" : "Not loaded"}</span>}
          {(c.eta || c.eta_text) && <span>ETA {c.eta ? when(c.eta) : c.eta_text}</span>}
          {c.delay_reason && <span className="text-red-600">{c.delay_reason}</span>}
        </div>
      )}
      {(c.message || c.notes) && (
        <p className="mt-1.5 pl-6 text-sm text-zinc-500">{c.channel === "sms" && c.message ? `“${c.message}”` : c.notes}</p>
      )}
      {c.entered_by && <p className="mt-1 pl-6 text-xs text-zinc-500">Entered by {c.entered_by}</p>}
      {c.call_id && (c.transcript?.length || c.has_recording) ? (
        <div className="mt-2 pl-6">
          <button onClick={() => setOpen(!open)} className="text-xs font-medium text-brand-700 hover:underline">
            {open ? "Hide" : "Show"} transcript{c.has_recording ? " and recording" : ""}
          </button>
          {open && (
            <div className="mt-2 space-y-2">
              {c.has_recording && <RecordingPlayer callId={c.call_id} live={false} />}
              <div className="space-y-1 rounded-lg bg-zinc-50 p-3 text-sm">
                {(c.transcript ?? []).map((t, i) => (
                  <p key={i}><span className="font-medium text-zinc-500">{t.role === "assistant" ? "AI" : "Driver"}:</span> {t.text}</p>
                ))}
              </div>
              <Link href={`/calls/${c.call_id}`} className="text-xs text-zinc-500 hover:underline">Open the call log</Link>
            </div>
          )}
        </div>
      ) : null}
    </li>
  );
}

function DriverCard({ detail, onSaved }: { detail: LoadDetail; onSaved: () => void }) {
  const toast = useToast();
  const l = detail.load;
  const [name, setName] = useState(l.driver_name);
  const [phone, setPhone] = useState(l.driver_phone);
  const [notes, setNotes] = useState(l.notes);
  const [saving, setSaving] = useState(false);
  async function save(extra: Record<string, unknown> = {}) {
    setSaving(true);
    try {
      await patch(`/api/track-desk/loads/${l.id}`, { driver_name: name, driver_phone: phone, notes, ...extra });
      onSaved();
      toast("Saved");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }
  return (
    <Card>
      <CardHeader title="Driver" description={formatPhone(l.driver_phone)} />
      <div className="space-y-3 p-5">
        <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Phone" hint="Changing the number lets us contact the new driver even if the old one opted out."><Input value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
        <Field label="Notes"><Input value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        <Toggle checked={l.sms_only} onChange={(v) => save({ sms_only: v })} label="Text only" description="Text this driver instead of calling." />
        <Button loading={saving} onClick={() => save()}>Save driver</Button>
      </div>
    </Card>
  );
}

function ManualCheckIn({ open, onClose, loadId, onSaved }: { open: boolean; onClose: () => void; loadId: string; onSaved: () => void }) {
  const toast = useToast();
  const [location, setLocation] = useState("");
  const [eta, setEta] = useState("");
  const [loaded, setLoaded] = useState("unknown");
  const [delay, setDelay] = useState("");
  const [delivered, setDelivered] = useState(false);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    try {
      await post(`/api/track-desk/loads/${loadId}/manual-check-in`, {
        location_text: location, eta: eta ? new Date(eta).toISOString() : null, loaded, delay_reason: delay, delivered,
      });
      onSaved();
      onClose();
      setLocation(""); setEta(""); setDelay(""); setDelivered(false);
      toast("Check-in logged");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Add a check-in">
      <div className="space-y-3">
        <Field label="Location"><Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="I-40 near Amarillo, TX" /></Field>
        <Field label="ETA"><Input type="datetime-local" value={eta} onChange={(e) => setEta(e.target.value)} /></Field>
        <Field label="Loaded">
          <Select value={loaded} onChange={(e) => setLoaded(e.target.value)}>
            <option value="unknown">Not sure</option><option value="yes">Loaded, rolling</option><option value="no">Not loaded yet</option>
          </Select>
        </Field>
        <Field label="Delay (if any)"><Input value={delay} onChange={(e) => setDelay(e.target.value)} placeholder="Detention at shipper" /></Field>
        <Toggle checked={delivered} onChange={setDelivered} label="Delivered" />
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={save}>Log check-in</Button>
        </div>
      </div>
    </Modal>
  );
}
