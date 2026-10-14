"use client";

import { MessageSquareText } from "lucide-react";
import { useState, type FormEvent } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Field, Input, Notice } from "@/components/ui";
import { del, fetcher, post, put } from "@/lib/api";
import { cn } from "@/lib/utils";

type Provider = "twilio" | "telnyx";

interface Messaging {
  connected: boolean;
  provider?: Provider;
  account_sid?: string;
  from_number?: string;
  messaging_profile_id?: string;
  account_label?: string;
  last_error?: string | null;
  last_sent_at?: string | null;
}

const NAMES: Record<Provider, string> = { twilio: "Twilio", telnyx: "Telnyx" };

/** The account's own texting provider: paste Twilio or Telnyx credentials so agents can text from their number. */
export function TextingCard() {
  const toast = useToast();
  const { data, mutate } = useSWR<Messaging>("/api/phone-numbers/messaging", fetcher);
  const [editing, setEditing] = useState(false);
  const [provider, setProvider] = useState<Provider>("twilio");
  const [sid, setSid] = useState("");
  const [secret, setSecret] = useState("");
  const [from, setFrom] = useState("");
  const [profile, setProfile] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | "remove" | null>(null);
  const [error, setError] = useState("");
  const [testTo, setTestTo] = useState("");

  if (!data) return null;
  const connected = data.connected && !editing;
  const updating = data.connected && editing && data.provider === provider; // blank secret keeps the saved one

  function startEdit() {
    setProvider(data!.provider ?? "twilio");
    setSid("");
    setSecret("");
    setFrom(data!.from_number ?? "");
    setProfile(data!.messaging_profile_id ?? "");
    setError("");
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy("save");
    setError("");
    try {
      await put("/api/phone-numbers/messaging", {
        provider,
        account_sid: sid.trim(),
        secret: secret.trim(),
        from_number: from.trim(),
        messaging_profile_id: profile.trim(),
      });
      await mutate();
      setEditing(false);
      setSecret("");
      toast("Texting connected");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function sendTest(e: FormEvent) {
    e.preventDefault();
    setBusy("test");
    try {
      const r = await post<{ to: string }>("/api/phone-numbers/messaging/test", { to: testTo.trim() });
      toast(`Test text sent to ${r.to}`);
      await mutate();
    } catch (err) {
      toast((err as Error).message, "error");
      await mutate();
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!confirm("Disconnect texting? Agents won't be able to send texts until you connect again.")) return;
    setBusy("remove");
    try {
      await del("/api/phone-numbers/messaging");
      await mutate();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <MessageSquareText className="h-4 w-4 text-brand-600" /> Texting (SMS)
            {data.connected && <Badge tone="green">Connected</Badge>}
          </span>
        }
        description={
          data.connected
            ? undefined
            : "Add your own credentials to start sending — so your agents can text from your number."
        }
      />
      <div className="space-y-4 p-5">
        {connected ? (
          <>
            <div className="text-sm">
              <div className="font-medium text-zinc-900">
                {NAMES[data.provider ?? "twilio"]} · {data.from_number}
              </div>
              <div className="text-xs text-zinc-500">
                {[data.account_label, data.account_sid].filter(Boolean).join(" · ")}
              </div>
            </div>
            {data.last_error && <Notice tone="red">Last text failed: {data.last_error}</Notice>}
            <form onSubmit={sendTest} className="flex items-end gap-2">
              <Field label="Send a test text" className="flex-1">
                <Input value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="Your mobile, e.g. +14155550123" inputMode="tel" />
              </Field>
              <Button type="submit" loading={busy === "test"} disabled={testTo.trim().length < 10}>
                Send
              </Button>
            </form>
            <div className="flex gap-2">
              <Button size="sm" onClick={startEdit}>
                Change
              </Button>
              <Button size="sm" variant="ghost" loading={busy === "remove"} onClick={() => void disconnect()}>
                Disconnect
              </Button>
            </div>
          </>
        ) : (
          <form onSubmit={save} className="space-y-3">
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-zinc-100 p-1 text-sm">
              {(["twilio", "telnyx"] as Provider[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setProvider(p)}
                  className={cn("rounded-md py-1.5 font-medium", provider === p ? "bg-white text-zinc-900 shadow-xs" : "text-zinc-500 hover:text-zinc-800")}
                >
                  {NAMES[p]}
                </button>
              ))}
            </div>
            {provider === "twilio" ? (
              <>
                <Field label="Account SID" hint={updating ? "Leave blank to keep the saved one." : "From your Twilio console home page — starts with AC."}>
                  <Input value={sid} onChange={(e) => setSid(e.target.value)} placeholder={updating ? data.account_sid : "AC…"} autoComplete="off" spellCheck={false} />
                </Field>
                <Field label="Auth Token" hint={updating ? "Leave blank to keep the saved token." : undefined}>
                  <Input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={updating ? "••••••••" : ""} autoComplete="new-password" />
                </Field>
              </>
            ) : (
              <>
                <Field label="API key" hint={updating ? "Leave blank to keep the saved key." : "Telnyx portal → Account settings → API keys."}>
                  <Input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={updating ? "••••••••" : "KEY…"} autoComplete="new-password" />
                </Field>
                <Field label="Messaging profile ID" hint="Optional — only if your number isn't already assigned to one.">
                  <Input value={profile} onChange={(e) => setProfile(e.target.value)} autoComplete="off" spellCheck={false} />
                </Field>
              </>
            )}
            <Field label="Number to text from" hint={`A number in your ${NAMES[provider]} account that's set up for texting.`}>
              <Input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="+14155550123" inputMode="tel" />
            </Field>
            {error && <Notice tone="red">{error}</Notice>}
            <p className="text-xs text-zinc-500">
              US carriers only deliver business texts from registered numbers (A2P 10DLC) — register yours in your {NAMES[provider]} account first.
              Your credentials are encrypted and never shown again.
            </p>
            <div className="flex gap-2">
              <Button type="submit" variant="primary" loading={busy === "save"} disabled={!from.trim() || (!updating && !secret.trim())}>
                {data.connected ? "Save" : "Connect"}
              </Button>
              {editing && (
                <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              )}
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
