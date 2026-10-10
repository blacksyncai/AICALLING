"use client";

import { Mail, Trash2, UserPlus, Users, X } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice, Select, Spinner } from "@/components/ui";
import { del, fetcher, patch, post } from "@/lib/api";
import { displayName, useSession } from "@/lib/session";
import type { CreatedInvite, Member, OrgDetail, PendingInvite, Role } from "@/lib/types";
import { formatDateTime, timeAgo } from "@/lib/utils";
import { Avatar, CopyButton, ROLE_INFO, ROLE_TONE } from "./shared";

function InviteForm({ onCreated }: { onCreated: (inv: CreatedInvite) => void }) {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const inv = await post<CreatedInvite>("/api/account/org/invites", { email: email.trim(), role });
      setEmail("");
      setRole("member");
      onCreated(inv);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-end">
      <Field label="Email address" className="min-w-0 flex-1">
        <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com" required />
      </Field>
      <Field label="Role" className="sm:w-36">
        <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLE_INFO.map((r) => (
            <option key={r.role} value={r.role}>
              {r.label}
            </option>
          ))}
        </Select>
      </Field>
      <Button variant="primary" loading={busy} disabled={!email.trim()}>
        <UserPlus className="h-4 w-4" /> Send invite
      </Button>
    </form>
  );
}

function MemberRow({
  m,
  isMe,
  canManage,
  onChanged,
  onRemove,
}: {
  m: Member;
  isMe: boolean;
  canManage: boolean;
  onChanged: () => void;
  onRemove: (m: Member) => void;
}) {
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const name = displayName(m);

  async function changeRole(role: Role) {
    if (role === m.role) return;
    setSaving(true);
    try {
      await patch(`/api/account/org/members/${m.membership_id}`, { role });
      toast(`${name} is now ${role === "admin" ? "an admin" : `a ${role}`}`);
      onChanged();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
      <div className="flex min-w-[12rem] flex-1 items-center gap-3">
        <Avatar name={name} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-zinc-900">{name}</span>
            {isMe && <Badge className="shrink-0">You</Badge>}
          </div>
          <div className="truncate text-xs text-zinc-500">{m.email}</div>
          <div className="truncate text-xs text-zinc-400 sm:hidden">
            {m.last_login_at ? `Active ${timeAgo(m.last_login_at)}` : "Never signed in"}
          </div>
        </div>
      </div>
      <div className="ml-12 flex items-center gap-3 sm:ml-0">
        <span className="hidden text-xs text-zinc-500 sm:inline" title={m.last_login_at ? formatDateTime(m.last_login_at) : undefined}>
          {m.last_login_at ? `Active ${timeAgo(m.last_login_at)}` : "Never signed in"}
        </span>
        {canManage && !isMe ? (
          <Select
            value={m.role}
            onChange={(e) => changeRole(e.target.value as Role)}
            disabled={saving}
            className="h-8 w-28 text-xs"
            aria-label={`Role for ${name}`}
          >
            {ROLE_INFO.map((r) => (
              <option key={r.role} value={r.role}>
                {r.label}
              </option>
            ))}
          </Select>
        ) : (
          <Badge tone={ROLE_TONE[m.role]} className="capitalize">
            {m.role}
          </Badge>
        )}
        {canManage &&
          (isMe ? (
            <span className="w-8" />
          ) : (
            <button
              onClick={() => onRemove(m)}
              className="rounded-md p-2 text-zinc-400 hover:bg-red-50 hover:text-red-600"
              aria-label={`Remove ${name}`}
              title="Remove from team"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          ))}
      </div>
    </li>
  );
}

export function TeamTab() {
  const { session } = useSession();
  const toast = useToast();
  const { data, error, mutate } = useSWR<OrgDetail>("/api/account/org", fetcher);
  const [link, setLink] = useState<CreatedInvite | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  if (error) return <Card><EmptyState icon={<Users className="h-5 w-5" />} title="Couldn't load your team" description={error.message} /></Card>;
  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  const manage = data.can_manage;

  function onCreated(inv: CreatedInvite) {
    mutate();
    if (inv.emailed) toast(`Invite sent to ${inv.email}`);
    else setLink(inv);
  }

  async function confirmRemove() {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await del(`/api/account/org/members/${removing.membership_id}`);
      toast(`${displayName(removing)} was removed`);
      setRemoving(null);
      mutate();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setRemoveBusy(false);
    }
  }

  async function revoke(inv: PendingInvite) {
    setRevoking(inv.id);
    try {
      await del(`/api/account/org/invites/${inv.id}`);
      toast(`Invite to ${inv.email} revoked`);
      mutate();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="space-y-6">
      {manage && (
        <Card>
          <CardHeader
            title="Invite a teammate"
            description={
              data.email_enabled
                ? "We'll email them a link to join. Invites expire after 7 days."
                : "You'll get a link to send them yourself. Invites expire after 7 days."
            }
          />
          <InviteForm onCreated={onCreated} />
        </Card>
      )}

      <Card>
        <CardHeader
          title="Members"
          description={`${data.members.length} ${data.members.length === 1 ? "person" : "people"} in ${data.name}`}
        />
        {!manage && (
          <div className="border-b border-zinc-100 px-5 py-3">
            <Notice tone="blue">Only owners and admins can invite people or change roles.</Notice>
          </div>
        )}
        <ul className="divide-y divide-zinc-100">
          {data.members.map((m) => (
            <MemberRow
              key={m.membership_id}
              m={m}
              isMe={m.id === session?.user.id}
              canManage={manage}
              onChanged={() => mutate()}
              onRemove={setRemoving}
            />
          ))}
        </ul>
      </Card>

      {data.invites.length > 0 && (
        <Card>
          <CardHeader title="Pending invites" description="People who've been invited but haven't joined yet." />
          <ul className="divide-y divide-zinc-100">
            {data.invites.map((inv) => (
              <li key={inv.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
                <div className="flex min-w-[12rem] flex-1 items-center gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-dashed border-zinc-300 text-zinc-400">
                    <Mail className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-zinc-900">{inv.email}</div>
                    <div className="truncate text-xs text-zinc-500">
                      Invited {timeAgo(inv.created_at)}
                      {inv.expires_at && ` · expires ${formatDateTime(inv.expires_at)}`}
                    </div>
                  </div>
                </div>
                <div className="ml-12 flex items-center gap-3 sm:ml-0">
                  <Badge tone={ROLE_TONE[inv.role]} className="capitalize">
                    {inv.role}
                  </Badge>
                  {manage && (
                    <Button size="sm" variant="ghost" loading={revoking === inv.id} onClick={() => revoke(inv)}>
                      <X className="h-3.5 w-3.5" /> Revoke
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <CardHeader title="Roles" description="What each role can do in this account." />
        <dl className="grid gap-px overflow-hidden rounded-b-xl bg-zinc-100 sm:grid-cols-3">
          {ROLE_INFO.map((r) => (
            <div key={r.role} className="bg-white px-5 py-4">
              <dt>
                <Badge tone={ROLE_TONE[r.role]}>{r.label}</Badge>
              </dt>
              <dd className="mt-2 text-xs leading-relaxed text-zinc-600">{r.description}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <Modal open={!!link} onClose={() => setLink(null)} title="Share the invite link">
        {link && (
          <div className="space-y-4">
            <Notice tone="amber">Email isn&apos;t set up yet — send this link to them yourself. It expires in 7 days.</Notice>
            <p className="text-sm text-zinc-600">
              Invite for <span className="font-medium text-zinc-900">{link.email}</span> as{" "}
              <span className="font-medium capitalize text-zinc-900">{link.role}</span>.
            </p>
            <div className="flex min-w-0 items-center gap-2">
              <Input readOnly value={link.invite_url} onFocus={(e) => e.currentTarget.select()} className="min-w-0 flex-1 font-mono text-xs" />
              <CopyButton text={link.invite_url} />
            </div>
            <div className="flex justify-end">
              <Button variant="primary" onClick={() => setLink(null)}>
                Done
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!removing} onClose={() => setRemoving(null)} title="Remove member">
        {removing && (
          <div className="space-y-4">
            <p className="text-sm text-zinc-600">
              Remove <span className="font-medium text-zinc-900">{displayName(removing)}</span> ({removing.email}) from {data.name}? They&apos;ll
              lose access immediately. Their calls and contacts stay in the account.
            </p>
            <div className="flex justify-end gap-2">
              <Button onClick={() => setRemoving(null)}>Cancel</Button>
              <Button variant="danger" loading={removeBusy} onClick={confirmRemove}>
                Remove
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
