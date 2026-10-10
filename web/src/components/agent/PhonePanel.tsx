"use client";

import { ExternalLink, Phone } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { post } from "@/lib/api";
import { Button, Field, Input, Notice } from "../ui";

export function PhonePanel({ agentId, enabled, beforeStart }: { agentId: string; enabled: boolean; beforeStart: () => Promise<boolean> }) {
  const [phone, setPhone] = useState("");
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
      const res = await post<{ call_id: string }>(`/api/agents/${agentId}/phone-call`, { to_phone: phone.trim() });
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
