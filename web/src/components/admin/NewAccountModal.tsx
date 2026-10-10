"use client";

import { KeyRound, Mail } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, Field, Input, Modal, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { post } from "@/lib/api";
import type { CreatedOrg } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CopyField } from "./shared";

type Mode = "password" | "invite";

const EMPTY = { name: "", first: "", last: "", email: "", phone: "", credits: "0", leadCredits: "0", password: "" };

export function NewAccountModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const router = useRouter();
  const [form, setForm] = useState(EMPTY);
  const [mode, setMode] = useState<Mode>("password");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<CreatedOrg | null>(null);

  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const close = () => {
    onClose();
    // Reset after the modal is gone so the one-time secrets don't linger.
    setTimeout(() => {
      setForm(EMPTY);
      setMode("password");
      setResult(null);
    }, 0);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.email.trim()) return;
    setSaving(true);
    try {
      const created = await post<CreatedOrg>("/api/admin/orgs", {
        name: form.name.trim(),
        owner_first_name: form.first.trim(),
        owner_last_name: form.last.trim(),
        owner_email: form.email.trim(),
        owner_phone: form.phone.trim(),
        password: mode === "password" ? form.password : "",
        send_invite: mode === "invite",
        credits: Math.max(0, Number(form.credits) || 0),
        lead_credits: Math.max(0, Number(form.leadCredits) || 0),
      });
      setResult(created);
      onCreated();
      toast(`Created ${created.name}`);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={close} title={result ? "Account created" : "New account"}>
      {result ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-zinc-600">
            <span className="font-medium text-zinc-900">{result.name}</span> is ready
            {result.credits_balance > 0 ? ` with ${result.credits_balance.toLocaleString()} credits` : ""}.
          </p>

          {result.owner_status === "created" && (
            <>
              <CopyField label="Login email" value={result.login_email} mono={false} />
              {result.temporary_password ? (
                <>
                  <CopyField label="Temporary password" value={result.temporary_password} />
                  <Notice tone="amber">This password is shown once. Copy it now and send it to the owner securely — they can change it after signing in.</Notice>
                </>
              ) : (
                <Notice tone="blue">The owner can sign in with the password you set.</Notice>
              )}
            </>
          )}

          {result.owner_status === "invited" && (
            <>
              {result.invite_url && <CopyField label="Invite link" value={result.invite_url} />}
              <Notice tone={result.emailed ? "green" : "amber"}>
                {result.emailed
                  ? `An invite email was sent to ${result.login_email}. You can also share the link above.`
                  : `Email isn't configured, so nothing was sent. Share this link with ${result.login_email} yourself.`}
              </Notice>
            </>
          )}

          {result.owner_status === "existing_user_added" && (
            <Notice tone="blue">
              <span className="font-medium">{result.login_email}</span> already had a BlackSync login, so they were added as the owner of this account. They sign in with
              their existing password.
            </Notice>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={close}>
              Close
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                const id = result.id;
                close();
                router.push(`/admin/accounts/${id}`);
              }}
            >
              Go to account
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Company name *">
            <Input value={form.name} onChange={set("name")} placeholder="Acme Inc." required autoFocus />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Owner first name">
              <Input value={form.first} onChange={set("first")} autoComplete="off" />
            </Field>
            <Field label="Owner last name">
              <Input value={form.last} onChange={set("last")} autoComplete="off" />
            </Field>
          </div>
          <Field label="Owner email *">
            <Input type="email" value={form.email} onChange={set("email")} placeholder="owner@company.com" required autoComplete="off" />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Owner phone">
              <Input type="tel" value={form.phone} onChange={set("phone")} placeholder="+1 555 000 0000" autoComplete="off" />
            </Field>
            <Field label="Starting calling credits" hint="1 credit = 1 minute of calling">
              <Input type="number" min={0} step={1} value={form.credits} onChange={set("credits")} />
            </Field>
          </div>
          <Field label="Starting lookup credits" hint="Lead Finder — 1 credit per property owner found">
            <Input type="number" min={0} step={1} value={form.leadCredits} onChange={set("leadCredits")} />
          </Field>

          <div>
            <div className="mb-1.5 text-xs font-medium text-zinc-700">Owner access</div>
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup">
              {(
                [
                  { v: "password", icon: KeyRound, title: "Set a password now", desc: "You hand over the login yourself" },
                  { v: "invite", icon: Mail, title: "Email an invite link", desc: "They pick their own password" },
                ] as const
              ).map((o) => (
                <button
                  key={o.v}
                  type="button"
                  role="radio"
                  aria-checked={mode === o.v}
                  onClick={() => setMode(o.v)}
                  className={cn(
                    "flex items-start gap-2.5 rounded-lg border p-3 text-left transition-colors",
                    mode === o.v ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-zinc-200 hover:bg-zinc-50",
                  )}
                >
                  <o.icon className={cn("mt-0.5 h-4 w-4 shrink-0", mode === o.v ? "text-brand-600" : "text-zinc-400")} />
                  <span>
                    <span className="block text-sm font-medium text-zinc-900">{o.title}</span>
                    <span className="block text-xs text-zinc-500">{o.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          {mode === "password" && (
            <Field label="Password" hint="Leave blank to auto-generate a temporary password.">
              <Input type="text" value={form.password} onChange={set("password")} placeholder="Auto-generate" autoComplete="new-password" className="font-mono" />
            </Field>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={saving} disabled={!form.name.trim() || !form.email.trim()}>
              Create account
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
