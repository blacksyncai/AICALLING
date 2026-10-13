"use client";

import { KeyRound, Mail, Receipt, UserPlus } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice, Select, Toggle } from "@/components/ui";
import { useToast } from "@/components/toast";
import { patch, post } from "@/lib/api";
import { displayName } from "@/lib/session";
import type { AdminOrgDetail, CreatedInvite, CreditTransaction, Role } from "@/lib/types";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";
import { Avatar, CopyField, fmt } from "./shared";

type Props = { org: AdminOrgDetail; refresh: () => void };

const KIND_TONE: Record<CreditTransaction["kind"], "green" | "gray" | "blue"> = { grant: "green", usage: "gray", adjustment: "blue" };
const ROLE_TONE: Record<Role, "brand" | "blue" | "gray"> = { owner: "brand", admin: "blue", member: "gray" };

// ── Credits ───────────────────────────────────────────────────────────────────

export function CreditsCard({ org, refresh }: Props) {
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"add" | "remove" | null>(null);

  const apply = async (sign: 1 | -1) => {
    const n = Math.abs(Math.round(Number(amount)));
    if (!n) return toast("Enter a number of credits", "error");
    setBusy(sign > 0 ? "add" : "remove");
    try {
      const res = await post<{ balance: number; transaction: CreditTransaction }>(`/api/admin/orgs/${org.id}/credits`, { amount: sign * n, note: note.trim() });
      toast(`${sign > 0 ? "Added" : "Removed"} ${fmt(n)} credits · balance ${fmt(res.balance)}`);
      setAmount("");
      setNote("");
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  const low = !org.unlimited_credits && org.credits_balance <= 10;

  return (
    <Card className="min-w-0">
      <CardHeader title="Credits" description="1 credit = 1 minute of phone calling" />
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className={cn("font-display text-4xl font-semibold tabular-nums tracking-tight", low ? "text-amber-700" : "text-zinc-900")}>{fmt(org.credits_balance)}</span>
          <span className="text-sm text-zinc-500">credits left</span>
          {org.unlimited_credits && <Badge tone="violet">Unlimited — balance not enforced</Badge>}
          {low && <Badge tone="amber">Low balance</Badge>}
        </div>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            apply(1);
          }}
          className="flex flex-col gap-3"
        >
          <div className="grid gap-3 sm:grid-cols-[140px_1fr]">
            <Field label="Amount">
              <Input type="number" min={1} step={1} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0" />
            </Field>
            <Field label="Note">
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Monthly plan top-up" />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {[60, 300, 1000].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setAmount(String((Number(amount) || 0) + n))}
                className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700"
              >
                +{fmt(n)}
              </button>
            ))}
            <div className="ml-auto flex gap-2">
              <Button type="button" variant="secondary" loading={busy === "remove"} disabled={!!busy || !Number(amount)} onClick={() => apply(-1)}>
                Remove
              </Button>
              <Button type="submit" variant="primary" loading={busy === "add"} disabled={!!busy || !Number(amount)}>
                Add credits
              </Button>
            </div>
          </div>
        </form>
      </div>
    </Card>
  );
}

// ── Ledger ────────────────────────────────────────────────────────────────────

export function LedgerCard({ org }: { org: AdminOrgDetail }) {
  return (
    <Card className="min-w-0">
      <CardHeader title="Credit ledger" description="Grants, call usage and manual adjustments" />
      {org.transactions.length === 0 ? (
        <EmptyState icon={<Receipt className="h-5 w-5" />} title="No transactions yet" description="Credits added or used by calls will show up here." />
      ) : (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="sticky top-0 border-b border-zinc-100 bg-white text-left text-xs text-zinc-500">
              <tr>
                <th className="px-5 py-2.5 font-medium">Date</th>
                <th className="px-3 py-2.5 font-medium">Note</th>
                <th className="px-3 py-2.5 font-medium">Type</th>
                <th className="px-3 py-2.5 text-right font-medium">Amount</th>
                <th className="px-5 py-2.5 text-right font-medium">Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {org.transactions.map((t) => (
                <tr key={t.id}>
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs text-zinc-500">{formatDateTime(t.created_at)}</td>
                  <td className="max-w-[240px] truncate px-3 py-2.5 text-zinc-700" title={t.note}>
                    {t.note || <span className="text-zinc-400">—</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge tone={KIND_TONE[t.kind] ?? "gray"}>{t.kind}</Badge>
                  </td>
                  <td className={cn("whitespace-nowrap px-3 py-2.5 text-right font-medium tabular-nums", t.amount > 0 ? "text-emerald-700" : "text-zinc-900")}>
                    {t.amount > 0 ? "+" : t.amount < 0 ? "−" : ""}
                    {fmt(Math.abs(t.amount))}
                  </td>
                  <td className="px-5 py-2.5 text-right tabular-nums text-zinc-600">{fmt(t.balance_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ── Settings ──────────────────────────────────────────────────────────────────

export function SettingsCard({ org, refresh }: Props) {
  const toast = useToast();
  const [name, setName] = useState(org.name);
  const [saving, setSaving] = useState<"name" | "unlimited" | "status" | null>(null);
  const [confirmStatus, setConfirmStatus] = useState(false);

  useEffect(() => setName(org.name), [org.name]);

  const save = async (key: "name" | "unlimited" | "status", body: Record<string, unknown>, msg: string) => {
    setSaving(key);
    try {
      await patch(`/api/admin/orgs/${org.id}`, body);
      toast(msg);
      refresh();
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    } finally {
      setSaving(null);
    }
  };

  const suspended = org.status === "suspended";

  return (
    <Card className="min-w-0">
      <CardHeader title="Settings" />
      <div className="flex flex-col gap-4 p-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && name.trim() !== org.name) save("name", { name: name.trim() }, "Account renamed");
          }}
        >
          <Field label="Account name">
            <div className="flex gap-2">
              <Input value={name} onChange={(e) => setName(e.target.value)} className="min-w-0" />
              <Button type="submit" loading={saving === "name"} disabled={!name.trim() || name.trim() === org.name}>
                Save
              </Button>
            </div>
          </Field>
        </form>

        <Toggle
          checked={org.unlimited_credits}
          onChange={(v) => saving !== "unlimited" && save("unlimited", { unlimited_credits: v }, v ? "Unlimited credits on" : "Unlimited credits off")}
          label="Unlimited credits"
          description="Calls aren't blocked when the balance runs out. Usage is still recorded."
        />

        <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-900">
              Account status <Badge tone={suspended ? "red" : "green"}>{org.status}</Badge>
            </div>
            <p className="mt-0.5 text-xs text-zinc-500">Suspended accounts can still sign in and see their data, but can't place calls.</p>
          </div>
          <Button variant={suspended ? "primary" : "danger"} size="sm" className="shrink-0" onClick={() => setConfirmStatus(true)}>
            {suspended ? "Reactivate" : "Suspend"}
          </Button>
        </div>
      </div>

      <Modal open={confirmStatus} onClose={() => setConfirmStatus(false)} title={suspended ? "Reactivate account?" : "Suspend account?"}>
        <p className="text-sm text-zinc-600">
          {suspended ? (
            <>
              <span className="font-medium text-zinc-900">{org.name}</span> will be able to place calls and run campaigns again.
            </>
          ) : (
            <>
              <span className="font-medium text-zinc-900">{org.name}</span> will be blocked from placing calls. Its members can still sign in and see their data. You can
              reactivate it at any time.
            </>
          )}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmStatus(false)}>
            Cancel
          </Button>
          <Button
            variant={suspended ? "primary" : "danger"}
            loading={saving === "status"}
            onClick={async () => {
              const ok = await save("status", { status: suspended ? "active" : "suspended" }, suspended ? "Account reactivated" : "Account suspended");
              if (ok) setConfirmStatus(false);
            }}
          >
            {suspended ? "Reactivate" : "Suspend account"}
          </Button>
        </div>
      </Modal>
    </Card>
  );
}

// ── Team ──────────────────────────────────────────────────────────────────────

export function TeamCard({ org, refresh }: Props) {
  const toast = useToast();
  const [resetting, setResetting] = useState<string | null>(null);
  const [resetResult, setResetResult] = useState<{ email: string; temporary_password: string } | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [inviting, setInviting] = useState(false);
  const [invite, setInvite] = useState<CreatedInvite | null>(null);
  const [resending, setResending] = useState<string | null>(null);

  // Same email + role again: replaces the old link and emails a fresh one (e.g. invited before email was set up).
  const resend = async (i: { id: string; email: string; role: Role }) => {
    setResending(i.id);
    try {
      const created = await post<CreatedInvite>(`/api/admin/orgs/${org.id}/invites`, { email: i.email, role: i.role });
      setInvite(created);
      toast(created.emailed ? `Invite emailed to ${created.email}` : `New invite link created for ${created.email}`);
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setResending(null);
    }
  };

  const reset = async (userId: string) => {
    setResetting(userId);
    try {
      setResetResult(await post<{ email: string; temporary_password: string }>(`/api/admin/users/${userId}/reset-password`));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setResetting(null);
    }
  };

  const sendInvite = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setInviting(true);
    try {
      const created = await post<CreatedInvite>(`/api/admin/orgs/${org.id}/invites`, { email: email.trim(), role });
      setInvite(created);
      setEmail("");
      toast(created.emailed ? `Invite emailed to ${created.email}` : `Invite created for ${created.email}`);
      refresh();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setInviting(false);
    }
  };

  return (
    <Card className="min-w-0">
      <CardHeader title="Team" description={`${org.members.length} member${org.members.length === 1 ? "" : "s"}${org.invites.length ? ` · ${org.invites.length} pending` : ""}`} />

      <ul className="divide-y divide-zinc-100">
        {org.members.length === 0 && <li className="px-5 py-6 text-center text-sm text-zinc-500">No members yet.</li>}
        {org.members.map((m) => {
          const name = displayName(m);
          return (
            <li key={m.membership_id} className="flex items-center gap-3 px-5 py-3">
              <Avatar name={name} />
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-medium text-zinc-900">{name}</span>
                  <Badge tone={ROLE_TONE[m.role] ?? "gray"} className="shrink-0">
                    {m.role}
                  </Badge>
                </div>
                <div className="truncate text-xs text-zinc-500">
                  {m.email} · {m.last_login_at ? `last login ${timeAgo(m.last_login_at)}` : "never signed in"}
                </div>
              </div>
              <Button size="sm" variant="ghost" className="shrink-0" loading={resetting === m.id} onClick={() => reset(m.id)} title="Reset password">
                <KeyRound className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Reset password</span>
              </Button>
            </li>
          );
        })}
      </ul>

      {org.members.length > 0 && (
        <div className="border-t border-zinc-100 px-5 py-2.5 text-xs">
          <a href="/admin?tab=emails" className="inline-flex items-center gap-1.5 font-medium text-brand-700 hover:underline">
            <Mail className="h-3.5 w-3.5" /> Send a welcome or catch-up email
          </a>
        </div>
      )}

      {org.invites.length > 0 && (
        <div className="border-t border-zinc-100 px-5 py-4">
          <div className="mb-2 text-xs font-medium text-zinc-500">Pending invites</div>
          <ul className="flex flex-col gap-2">
            {org.invites.map((i) => (
              <li key={i.id} className="flex items-center gap-2 text-sm">
                <Mail className="h-4 w-4 shrink-0 text-zinc-400" />
                <span className="min-w-0 flex-1 truncate text-zinc-800">{i.email}</span>
                <Badge tone={ROLE_TONE[i.role] ?? "gray"} className="shrink-0">
                  {i.role}
                </Badge>
                <span className="hidden shrink-0 text-xs text-zinc-500 sm:inline">sent {timeAgo(i.created_at)}</span>
                <Button size="sm" variant="secondary" className="shrink-0" loading={resending === i.id} onClick={() => void resend(i as { id: string; email: string; role: Role })}>
                  <Mail className="h-3.5 w-3.5" /> Resend
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form onSubmit={sendInvite} className="flex flex-col gap-3 border-t border-zinc-100 px-5 py-4">
        <div className="text-xs font-medium text-zinc-700">Invite member</div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" required className="min-w-0 sm:flex-1" aria-label="Email" />
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)} className="sm:w-32" aria-label="Role">
            <option value="member">Member</option>
            <option value="admin">Admin</option>
            <option value="owner">Owner</option>
          </Select>
          <Button type="submit" variant="primary" loading={inviting} disabled={!email.trim()} className="shrink-0">
            <UserPlus className="h-4 w-4" /> Invite
          </Button>
        </div>
        {!org.email_enabled && <p className="text-xs text-zinc-500">Email isn&apos;t configured — you&apos;ll get a link to share yourself.</p>}
        {invite && (
          <div className="flex flex-col gap-2 rounded-lg border border-zinc-200 bg-zinc-50/60 p-3">
            {invite.emailed ? (
              <Notice tone="green">Invite emailed to {invite.email}.</Notice>
            ) : (
              <>
                <CopyField label={`Invite link for ${invite.email}`} value={invite.invite_url} />
                <p className="text-xs text-zinc-500">Not emailed — send this link to them directly.</p>
              </>
            )}
            <button type="button" onClick={() => setInvite(null)} className="self-end text-xs font-medium text-zinc-500 hover:text-zinc-800">
              Dismiss
            </button>
          </div>
        )}
      </form>

      <Modal open={!!resetResult} onClose={() => setResetResult(null)} title="Password reset">
        {resetResult && (
          <div className="flex flex-col gap-4">
            <CopyField label="Login email" value={resetResult.email} mono={false} />
            <CopyField label="Temporary password" value={resetResult.temporary_password} />
            <Notice tone="amber">This password is shown once. Their previous password no longer works — send this to them securely.</Notice>
            <div className="flex justify-end">
              <Button variant="primary" onClick={() => setResetResult(null)}>
                Done
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </Card>
  );
}
