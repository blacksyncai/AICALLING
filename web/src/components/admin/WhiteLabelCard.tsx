"use client";

import { Check, Copy, Globe, ImagePlus, Palette } from "lucide-react";
import { useState, type CSSProperties, type ChangeEvent } from "react";
import useSWR from "swr";
import { Badge, Button, Card, Field, Input, Notice, Spinner } from "@/components/ui";
import { useToast } from "@/components/toast";
import { del, fetcher, post, put } from "@/lib/api";

import { BrandKitFields } from "./BrandKitFields";
import { brandVariables, DEFAULT_KIT, primaryText, type BrandKit } from "@/lib/brand-theme";
import type { Brand } from "@/lib/branding";

type Config = {
  brand_kit: BrandKit; inherit_parent: boolean; parent?: { id: string; name: string } | null;
  inherited_brand?: Brand; effective_brand?: Brand;
  enabled: boolean; brand_name: string; domain: string; logo_url: string | null;
  domain_active: boolean; dns_verified: boolean; dns_verified_at: string | null;
  hosting_configured: boolean; clerk_enabled: boolean;
  dns_records: { type: string; name: string; value: string }[];
  verification?: { ownership: boolean; routing: boolean; verified: boolean };
};

export function WhiteLabelCard({ orgId }: { orgId: string }) {
  const url = `/api/admin/orgs/${orgId}/white-label`;
  const { data, error, mutate } = useSWR<Config>(url, fetcher, { revalidateOnFocus: false });
  return <Card id="white-label" className="scroll-mt-6 overflow-hidden">
    <div className="flex items-center gap-3 border-b border-zinc-100 px-6 py-5">
      <span className="rounded-xl bg-zinc-950 p-2.5 text-white"><Palette className="h-5 w-5" /></span>
      <div><h2 className="font-semibold text-zinc-900">Brand kit &amp; white label</h2><p className="text-xs text-zinc-500">Their name. Their logo. Their own front door.</p></div>
      <Badge className="ml-auto" tone="violet">Admin only</Badge>
    </div>
    {error ? <div className="p-6"><Notice tone="red">{error.message}</Notice></div>
      : !data ? <div className="flex justify-center p-8"><Spinner /></div>
      : <Editor key={`${orgId}:${data.brand_name}:${data.domain}:${data.enabled}:${JSON.stringify(data.brand_kit)}:${data.inherit_parent}`} data={data} url={url}
          update={async value => { await mutate(value, { revalidate: false }); }} />}
  </Card>;
}

function Editor({ data, url, update }: { data: Config; url: string; update: (data: Config) => Promise<void> }) {
  const toast = useToast();
  const [enabled, setEnabled] = useState(data.enabled);
  const [inherit, setInherit] = useState(!!data.parent && data.inherit_parent && !data.enabled);
  const [kit, setKit] = useState<BrandKit>(data.brand_kit ?? DEFAULT_KIT);
  const [name, setName] = useState(data.brand_name);
  const [domain, setDomain] = useState(data.domain);
  const [busy, setBusy] = useState<string | null>(null);
  const [hostingReady, setHostingReady] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const dirty = enabled !== data.enabled || name !== data.brand_name || domain !== data.domain
    || inherit !== (!!data.parent && data.inherit_parent && !data.enabled) || JSON.stringify(kit) !== JSON.stringify(data.brand_kit ?? DEFAULT_KIT);
  const preview = inherit ? data.inherited_brand?.name ?? "Parent brand" : name.trim() || "Your brand";
  const previewKit = inherit ? data.inherited_brand?.kit ?? DEFAULT_KIT : kit;
  const previewLogo = inherit ? data.inherited_brand?.logo_url : data.logo_url;
  const status = inherit && data.inherited_brand?.custom ? "Using parent brand kit" : !data.enabled ? "Branding off" : data.domain_active ? "Domain active" : data.dns_verified ? "Ready to activate" : data.domain ? "Waiting for DNS" : "Branding only";

  async function action(label: string, work: () => Promise<Config>) {
    setBusy(label);
    try { await update(await work()); toast(label === "verify" ? "DNS check complete" : "White label settings updated"); }
    catch (error) { toast((error as Error).message, "error"); }
    finally { setBusy(null); }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > 2_000_000) {
      toast("Choose a PNG, JPEG or WebP image smaller than 2 MB.", "error"); return;
    }
    await action("logo", async () => {
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("Couldn't read this image."));
        reader.readAsDataURL(file);
      });
      return put<Config>(`${url}/logo`, { image_base64: encoded });
    });
  }

  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); toast("Copied"); }
    catch { toast("Couldn't copy. Select and copy the value manually.", "error"); }
  }

  return <div className="grid gap-8 p-6 xl:grid-cols-[minmax(0,1fr)_280px]">
    <div className="min-w-0 space-y-6">
      <form className="space-y-4" onSubmit={event => {
        event.preventDefault();
        void action("save", () => put<Config>(url, { enabled, brand_name: name, domain, brand_kit: kit, inherit_parent: inherit }));
      }}>
        {data.parent && <label className="flex items-center gap-2 rounded-lg bg-zinc-50 p-3 text-sm"><input type="checkbox" checked={inherit} onChange={e => { setInherit(e.target.checked); setEnabled(!e.target.checked); if (!e.target.checked) { setKit(data.inherited_brand?.kit ?? DEFAULT_KIT); if (!name) setName(data.inherited_brand?.name ?? ""); } }} />Inherit the brand kit from {data.parent.name}</label>}
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" checked={enabled} disabled={inherit} onChange={event => setEnabled(event.target.checked)} className="h-4 w-4 accent-zinc-900" />
          Use this account&apos;s branding
        </label>
        <Field label="Brand name"><Input disabled={inherit} value={name} onChange={event => setName(event.target.value)} maxLength={100} required={enabled && !inherit} placeholder="Acme Voice" /></Field>
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2 text-xs font-medium hover:bg-zinc-50">
            <ImagePlus className="h-4 w-4" /> {busy === "logo" ? "Uploading…" : "Upload logo"}
            <input type="file" accept="image/png,image/jpeg,image/webp" aria-label="Upload brand logo" className="sr-only" disabled={!!busy || inherit} onChange={event => void upload(event)} />
          </label>
          {data.logo_url && <Button type="button" disabled={!!busy} onClick={() => void action("remove", () => del(`${url}/logo`).then(() => fetcher<Config>(url)))}>Remove logo</Button>}
          <span className="text-xs text-zinc-400">PNG, JPEG or WebP · up to 2 MB</span>
        </div>
        <BrandKitFields value={inherit ? previewKit : kit} onChange={setKit} disabled={inherit} />
        <Field label="Custom subdomain"><Input value={domain} onChange={event => setDomain(event.target.value)} placeholder="app.yourcompany.com" autoCapitalize="none" autoCorrect="off" spellCheck={false} /></Field>
        <p className="text-xs text-zinc-500">Enter the full hostname without https://. Leave blank to use their branding on the existing app address.</p>
        <Button variant="primary" loading={busy === "save"} disabled={!!busy && busy !== "save"}>Save branding</Button>
      </form>

      {data.domain && <section className="space-y-4 border-t border-zinc-100 pt-5">
        <div className="flex items-center gap-2"><Globe className="h-4 w-4 text-zinc-500" /><h3 className="text-sm font-semibold">Connect {data.domain}</h3></div>
        {!data.hosting_configured && <Notice tone="amber">The platform&apos;s custom-domain routing target hasn&apos;t been configured yet. Set WHITE_LABEL_CNAME_TARGET to the hosting provider&apos;s web-service alias before checking DNS.</Notice>}
        <p className="text-xs text-zinc-500">Add these records at the customer&apos;s DNS provider. Use DNS-only mode while verifying. Some providers expect only the name relative to their DNS zone.</p>
        <div className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200">
          {data.dns_records.map(record => <div key={record.type} className="space-y-2 p-3 text-xs">
            <span className="font-semibold text-zinc-700">{record.type}</span>
            {[["Name", record.name], ["Value", record.value]].map(([label, value]) => <div key={label} className="flex min-w-0 items-start gap-2">
              <span className="w-9 shrink-0 text-zinc-400">{label}</span><code className="min-w-0 flex-1 break-all text-zinc-700">{value}</code>
              <button type="button" onClick={() => void copy(value)} aria-label={`Copy ${record.type} ${label.toLowerCase()}`} className="shrink-0 text-zinc-400 hover:text-zinc-900"><Copy className="h-3.5 w-3.5" /></button>
            </div>)}
          </div>)}
        </div>
        {data.verification && <div className="flex flex-wrap gap-3 text-xs">
          <span className={data.verification.ownership ? "text-emerald-700" : "text-amber-700"}>Ownership TXT: {data.verification.ownership ? "verified" : "not found"}</span>
          <span className={data.verification.routing ? "text-emerald-700" : "text-amber-700"}>Routing CNAME: {data.verification.routing ? "verified" : "not found"}</span>
        </div>}
        {dirty && <p className="text-xs text-amber-700">Save your changes before checking or activating the domain.</p>}
        <Button disabled={!!busy || dirty || !data.hosting_configured} loading={busy === "verify"} onClick={() => void action("verify", () => post<Config>(`${url}/verify`))}>Check DNS records</Button>
        {data.dns_verified && !data.domain_active && <div className="space-y-3 rounded-xl bg-zinc-50 p-4">
          <h4 className="text-sm font-medium">Finish connecting the domain</h4>
          <p className="text-xs text-zinc-500">DNS verification proves ownership and routing. Add this exact hostname to the web hosting service and finish its HTTPS setup before activation.</p>
          <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={hostingReady} onChange={event => setHostingReady(event.target.checked)} className="mt-0.5" />The hostname is attached to hosting and its HTTPS certificate is ready.</label>
          <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={authReady} onChange={event => setAuthReady(event.target.checked)} className="mt-0.5" />{data.clerk_enabled ? "Clerk's custom-domain / satellite configuration and allowed sign-in redirects are ready." : "Sign-in has been configured for this hostname."}</label>
          <Button variant="primary" disabled={!!busy || dirty || !(data.effective_brand?.custom ?? data.enabled) || !hostingReady || !authReady} loading={busy === "activate"}
            onClick={() => void action("activate", () => post<Config>(`${url}/activate`, { hosting_ready: hostingReady, authentication_ready: authReady }))}>Activate custom domain</Button>
        </div>}
        {data.domain_active && <div className="flex flex-wrap items-center gap-3">
          <a href={`https://${data.domain}`} target="_blank" rel="noreferrer" className="text-xs font-medium text-emerald-700 hover:underline">Open branded workspace ↗</a>
          <Button disabled={!!busy || dirty} onClick={() => void action("deactivate", () => post<Config>(`${url}/deactivate`))}>Deactivate domain</Button>
        </div>}
      </section>}
    </div>
    <aside className="min-w-0 space-y-3">
      <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-3">
        <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">Brand preview</p>
        <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm" style={{ ...brandVariables(previewKit), fontFamily: "var(--font-sans)" } as CSSProperties}>
          <div className="flex h-24 items-center gap-3 px-5 text-white" style={{ background: previewKit.sidebar }}>
            {previewLogo ? <img src={previewLogo} alt="Uploaded brand logo" className="h-10 w-10 object-contain" /> : <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-zinc-800 text-lg">{preview.charAt(0)}</span>}
            <span className="truncate font-semibold">{preview}</span>
          </div>
          <div className="space-y-3 p-5"><h4 className="text-sm font-semibold">Welcome back</h4><p className="text-xs text-zinc-500">Sign in to your {preview} workspace.</p><div className="h-8 rounded-lg bg-zinc-100" /><div className="h-8 rounded-lg bg-zinc-100" /><div className="py-2 text-center text-xs" style={{ background: previewKit.primary, color: primaryText(previewKit.primary), borderRadius: "var(--brand-radius)" }}>Sign in</div></div>
        </div>
        <div className="mt-3 flex items-center gap-1.5 text-xs text-zinc-500"><Check className="h-3.5 w-3.5" /> Name, logo, colors and typography</div>
      </div>
      <Badge tone={data.domain_active ? "green" : "gray"}>{status}</Badge>
      <p className="text-xs leading-relaxed text-zinc-400">Only platform admins can change these settings. This updates the app identity; billing, legal notices, outgoing emails and voice-agent scripts keep their existing settings.</p>
    </aside>
  </div>;
}
