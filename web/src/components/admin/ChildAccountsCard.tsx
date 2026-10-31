"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { Building2, ChevronRight, Plus } from "lucide-react";
import { Button, Card, Field, Input, Notice, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import { useToast } from "@/components/toast";

type Family = { parent: { id: string; name: string } | null; children: {
  id: string; name: string; status: string; branding: { name: string; custom: boolean };
}[] };

export function ChildAccountsCard({ orgId }: { orgId: string }) {
  const url = `/api/admin/orgs/${orgId}/children`;
  const { data, error, mutate } = useSWR<Family>(url, fetcher);
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ temporary_password?: string | null; owner_status?: string } | null>(null);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setResult(null);
    try {
      const result = await post<{ temporary_password?: string | null; owner_status: string }>(url, { name, owner_email: email });
      setResult(result); setCreating(false); setName(""); setEmail(""); await mutate(); toast("Child account created");
    } catch (error) { toast((error as Error).message, "error"); }
    finally { setBusy(false); }
  }
  return <Card id="account-family" className="scroll-mt-6 p-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="flex items-center gap-2 font-semibold"><Building2 className="h-4 w-4" /> Account family</h2>
      <p className="mt-1 text-xs text-zinc-500">Separate client workspaces, organized under this account.</p></div>
      <Button onClick={() => setCreating(v => !v)}><Plus className="h-4 w-4" /> Add child account</Button></div>
    {error && <Notice tone="red">{error.message}</Notice>}
    {!data && !error && <div className="p-4"><Spinner /></div>}
    {data?.parent && <p className="mt-4 text-xs text-zinc-500">Parent account: <Link className="font-medium text-brand-700 hover:underline" href={`/admin/accounts/${data.parent.id}#account-family`}>{data.parent.name}</Link></p>}
    {data && <div className="mt-4 divide-y divide-zinc-100 rounded-xl border border-zinc-200">
      {!data.children.length && <p className="p-4 text-sm text-zinc-400">No child accounts yet.</p>}
      {data.children.map(child => <Link key={child.id} href={`/admin/accounts/${child.id}#white-label`} className="flex items-center gap-3 p-4 hover:bg-zinc-50">
        <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{child.name}</span><span className="text-xs text-zinc-400">{child.status} · {child.branding.custom ? child.branding.name : "BlackSync default"}</span></span><ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" /></Link>)}
    </div>}
    {creating && <form onSubmit={e => void submit(e)} className="mt-4 grid gap-3 rounded-xl bg-zinc-50 p-4 sm:grid-cols-2">
      <Field label="Child account name"><Input value={name} onChange={e => setName(e.target.value)} required maxLength={255} /></Field>
      <Field label="Owner email"><Input type="email" value={email} onChange={e => setEmail(e.target.value)} required /></Field>
      <p className="text-xs text-zinc-500 sm:col-span-2">Existing users receive an explicit owner membership. New users get a generated login. Credits and customer data remain separate; the parent brand kit is inherited by default.</p>
      <Button variant="primary" loading={busy}>Create child account</Button>
    </form>}
    {result && <div className="mt-4"><Notice tone="green">{result.temporary_password ? <>Owner login created. Save this password now: <code className="break-all font-mono">{result.temporary_password}</code></> : "Account created; the owner can use their existing login."}</Notice></div>}
    <p className="mt-3 text-xs text-zinc-400">Up to eight levels. Parent links never grant access to child contacts, calls, credits or settings. Only platform admins manage this hierarchy.</p>
  </Card>;
}
