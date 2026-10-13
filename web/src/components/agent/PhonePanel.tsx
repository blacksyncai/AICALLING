"use client";

import { ExternalLink, Phone } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { fetcher, post } from "@/lib/api";
import type { MyPhoneNumbers } from "@/lib/types";
import { Button, Field, Input, Notice, Select } from "../ui";

export function PhonePanel({
  agentId,
  enabled,
  beforeStart,
  callerNumber,
}: {
  agentId: string;
  enabled: boolean;
  beforeStart: () => Promise<boolean>;
  /** The agent's own "Call from" pick, if any — preselected. */
  callerNumber?: string | null;
}) {
  const [phone, setPhone] = useState("");
  // The account's numbers: with any, choose which one the test call comes from (none = platform line, as before).
  const { data: nums } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher);
  const numbers = (nums?.numbers ?? []).filter((n) => n.status === "active" || !n.status);
  const defaultFrom =
    numbers.find((n) => n.number === callerNumber)?.number ?? (numbers.find((n) => n.is_default) ?? numbers[0])?.number ?? "";
  const [fromPick, setFromPick] = useState<string | null>(null);
  const from = fromPick && numbers.some((n) => n.number === fromPick) ? fromPick : defaultFrom;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [callId, setCallId] = useState<string | null>(null);

  async function call(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setCallId(null);
    if (!(await beforeStart())) return;
    setBusy(true);
    try {
      const res = await post<{ call_id: string }>(`/api/agents/${agentId}/phone-call`, { to_phone: phone.trim(), from_number: from });
      setCallId(res.call_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={call} className="space-y-4">
      <p className="text-xs text-zinc-500">The agent will call this number right now — use your own phone to hear exactly what your leads will hear.</p>
      <Field label="Phone number" hint="E.164 format, including country code — e.g. +14155550123">
        <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+14155550123" disabled={!enabled} />
      </Field>
      {numbers.length > 0 && (
        <Field label="Call from" hint={numbers.length === 1 ? "Your account's number — the caller ID you'll see." : "The caller ID you'll see on your phone."}>
          <Select value={from} onChange={(e) => setFromPick(e.target.value)} disabled={!enabled}>
            {numbers.map((n) => (
              <option key={n.id} value={n.number}>
                {n.number}
                {n.label ? ` · ${n.label}` : ""}
                {n.number === callerNumber ? " (agent's number)" : n.is_default ? " (default)" : ""}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Button variant="primary" className="w-full" loading={busy} disabled={!enabled || phone.trim().length < 8}>
        <Phone className="h-4 w-4" /> Call me
      </Button>
      {!enabled && (
        <Notice>
          Phone calls need a LiveKit outbound SIP trunk (<code>LIVEKIT_SIP_OUTBOUND_TRUNK_ID</code>) on top of the voice keys.{" "}
          <Link href="/settings" className="font-medium underline">
            Setup guide
          </Link>
        </Notice>
      )}
      {error && <Notice tone="red">{error}</Notice>}
      {callId && (
        <Notice tone="green">
          Dialing… your phone should ring in a few seconds.{" "}
          <Link href={`/calls/${callId}`} className="inline-flex items-center gap-1 font-medium underline">
            Open call log <ExternalLink className="h-3 w-3" />
          </Link>
        </Notice>
      )}
    </form>
  );
}
