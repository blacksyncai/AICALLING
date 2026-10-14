"use client";

import { Check, Eye, Mail, Send } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Modal, Notice, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import { InvitesCard } from "./InvitesCard";
import { cn } from "@/lib/utils";

type Kind = "welcome" | "catchup" | "walkthrough";
interface Row {
  id: string;
  email: string;
  name: string;
  account: string | null;
  signed_up: string | null;
  last_login: string | null;
  superadmin: boolean;
  sent: Record<Kind, string | null>;
}
interface Overview {
  email_enabled: boolean;
  kinds: { key: Kind; name: string; description: string }[];
  users: Row[];
}
interface Preview {
  subject: string;
  html: string;
  to: string;
}

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—");

/** Admin → Emails: preview our customer emails and send them by hand (e.g. to people who signed up before email worked). */
export function EmailsTab() {
  const toast = useToast();
  const { data, error, mutate } = useSWR<Overview>("/api/admin/emails", fetcher);
  const [kind, setKind] = useState<Kind>("catchup");
  const [onlyMissing, setOnlyMissing] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [resend, setResend] = useState(false);
  const [sending, setSending] = useState(false);

  const users = useMemo(() => (data?.users ?? []).filter((u) => !u.superadmin), [data]);
  const shown = useMemo(() => (onlyMissing ? users.filter((u) => !u.sent[kind]) : users), [users, onlyMissing, kind]);
  const previewUser = previewFor ?? shown[0]?.id ?? users[0]?.id ?? null;
  const { data: preview, isLoading: previewLoading } = useSWR<Preview>(
    previewUser ? `/api/admin/emails/preview?kind=${kind}&user_id=${previewUser}` : null,
    fetcher,
  );

  useEffect(() => setSelected(new Set()), [kind]);

  if (error) return <Notice tone="red">Couldn&apos;t load emails: {error.message}</Notice>;
  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  const picked = users.filter((u) => selected.has(u.id));
  const alreadyGot = picked.filter((u) => u.sent[kind]);
  const kindInfo = data.kinds.find((k) => k.key === kind)!;
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  async function send() {
    setSending(true);
    try {
      const r = await post<{ sent: string[]; skipped: string[]; failed: string[] }>("/api/admin/emails/send", {
        kind,
        user_ids: picked.map((u) => u.id),
        resend,
      });
      toast(
        `Sent ${r.sent.length}${r.skipped.length ? ` · skipped ${r.skipped.length} (already had it)` : ""}${r.failed.length ? ` · ${r.failed.length} failed` : ""}`,
        r.failed.length ? "error" : "success",
      );
      setConfirm(false);
      setSelected(new Set());
      setResend(false);
      void mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-4">
      {!data.email_enabled && <Notice tone="amber">Email isn&apos;t set up on the server, so nothing can be sent.</Notice>}

      <InvitesCard emailEnabled={data.email_enabled} />

      <div className="grid gap-3 md:grid-cols-3">
        {data.kinds.map((k) => {
          const missing = users.filter((u) => !u.sent[k.key]).length;
          const on = k.key === kind;
          return (
            <button
              key={k.key}
              type="button"
              onClick={() => setKind(k.key)}
              className={cn(
                "rounded-2xl p-4 text-left ring-1 transition",
                on ? "bg-brand-50/60 ring-2 ring-brand-500" : "bg-white ring-zinc-200/80 hover:ring-zinc-300",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
                  <Mail className={cn("h-4 w-4", on ? "text-brand-600" : "text-zinc-400")} /> {k.name}
                </span>
                <Badge tone={missing ? "amber" : "green"}>{missing ? `${missing} haven't got it` : "Everyone has it"}</Badge>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">{k.description}</p>
            </button>
          );
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
        <Card className="overflow-hidden">
          <CardHeader
            title="Recipients"
            description={`Pick who gets “${kindInfo.name}”. People who already got it are skipped unless you choose to resend.`}
            action={
              <Button variant="primary" size="sm" className="whitespace-nowrap" disabled={!picked.length || !data.email_enabled} onClick={() => setConfirm(true)}>
                <Send className="h-3.5 w-3.5" /> {picked.length ? `Send to ${picked.length}` : "Send"}
              </Button>
            }
          />
          <div className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-5 py-2.5 text-xs">
            <label className="flex items-center gap-2 text-zinc-600">
              <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} className="accent-brand-600" />
              Only people who haven&apos;t received it
            </label>
            <button
              type="button"
              className="font-medium text-brand-700 hover:underline"
              onClick={() => setSelected(new Set(users.filter((u) => !u.sent[kind]).map((u) => u.id)))}
            >
              Select everyone who hasn&apos;t got it
            </button>
            {selected.size > 0 && (
              <button type="button" className="text-zinc-500 hover:underline" onClick={() => setSelected(new Set())}>
                Clear
              </button>
            )}
          </div>
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="sticky top-0 bg-white text-left text-[11px] uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="w-10 px-5 py-2" />
                  <th className="py-2 pr-3">Person</th>
                  <th className="py-2 pr-3">Account</th>
                  <th className="py-2 pr-3">Signed up</th>
                  <th className="py-2 pr-3">This email</th>
                  <th className="py-2 pr-5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {shown.map((u) => (
                  <tr key={u.id} className={cn("hover:bg-zinc-50", previewUser === u.id && "bg-brand-50/40")}>
                    <td className="px-5 py-2.5">
                      <input type="checkbox" checked={selected.has(u.id)} onChange={() => toggle(u.id)} className="accent-brand-600" aria-label={`Select ${u.email}`} />
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="font-medium text-zinc-900">{u.name || "—"}</div>
                      <div className="text-xs text-zinc-500">{u.email}</div>
                    </td>
                    <td className="py-2.5 pr-3 text-zinc-700">{u.account ?? "—"}</td>
                    <td className="py-2.5 pr-3 text-zinc-600">{day(u.signed_up)}</td>
                    <td className="py-2.5 pr-3">
                      {u.sent[kind] ? (
                        <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
                          <Check className="h-3.5 w-3.5" /> Sent {day(u.sent[kind])}
                        </span>
                      ) : (
                        <span className="text-xs text-zinc-400">Not sent</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-5 text-right">
                      <button type="button" onClick={() => setPreviewFor(u.id)} className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-brand-700">
                        <Eye className="h-3.5 w-3.5" /> Preview
                      </button>
                    </td>
                  </tr>
                ))}
                {!shown.length && (
                  <tr>
                    <td colSpan={6} className="px-5 py-10 text-center text-sm text-zinc-500">
                      Everyone has received this email.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="overflow-hidden xl:sticky xl:top-4 xl:self-start">
          <div className="border-b border-zinc-100 px-5 py-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Preview</div>
            <div className="mt-0.5 truncate text-sm font-semibold text-zinc-900">{preview?.subject ?? "…"}</div>
            <div className="truncate text-xs text-zinc-500">
              From notifications@blacksync.ai · To {preview?.to ?? "…"}
            </div>
          </div>
          {previewLoading || !preview ? (
            <div className="flex h-[560px] items-center justify-center">
              <Spinner />
            </div>
          ) : (
            <iframe title="Email preview" srcDoc={preview.html} sandbox="" className="h-[620px] w-full bg-[#f4f1ed]" />
          )}
        </Card>
      </div>

      <Modal open={confirm} onClose={() => !sending && setConfirm(false)} title={`Send “${kindInfo.name}”?`}>
        <div className="space-y-4 text-sm">
          <p className="text-zinc-700">
            This emails <strong>{picked.length}</strong> {picked.length === 1 ? "person" : "people"} from notifications@blacksync.ai:
          </p>
          <ul className="max-h-40 space-y-1 overflow-auto rounded-xl bg-zinc-50 p-3 text-xs text-zinc-600">
            {picked.map((u) => (
              <li key={u.id}>
                {u.name ? `${u.name} · ` : ""}
                {u.email}
                {u.sent[kind] && <span className="ml-1.5 text-amber-700">(already got it)</span>}
              </li>
            ))}
          </ul>
          {alreadyGot.length > 0 && (
            <label className="flex items-center gap-2 text-xs text-zinc-700">
              <input type="checkbox" checked={resend} onChange={(e) => setResend(e.target.checked)} className="accent-brand-600" />
              Also resend to the {alreadyGot.length} who already got it
            </label>
          )}
          <div className="flex justify-end gap-2">
            <Button onClick={() => setConfirm(false)} disabled={sending}>
              Cancel
            </Button>
            <Button variant="primary" loading={sending} onClick={() => void send()}>
              <Send className="h-4 w-4" /> Send now
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
