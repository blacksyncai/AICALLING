"use client";

import { CheckCircle2, ChevronRight, Download, ExternalLink, RefreshCw, Trash2, Zap } from "lucide-react";
import type React from "react";
import { useState } from "react";
import useSWR from "swr";
import { Badge, Button, Card, CardHeader, Field, Input, Modal, Notice, Select, Spinner, Toggle } from "@/components/ui";
import { del, fetcher, patch, post } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";

interface ProviderField {
  name: string;
  label: string;
  secret: boolean;
  placeholder: string;
  help: string;
}
interface Provider {
  key: string;
  name: string;
  category: "crm" | "notify" | "sheet";
  description: string;
  native: boolean;
  oauth: boolean;
  can_import: boolean;
  can_new_leads: boolean;
  docs_url: string;
  fields: ProviderField[];
}
interface Connection {
  provider: string;
  method: "api_key" | "nango";
  account_label: string;
  status: "connected" | "error";
  last_error: string | null;
  last_synced_at: string | null;
  settings: { log_calls: boolean; create_contacts: boolean; only_connected: boolean; speed_to_lead_agent_id: string | null };
  pending_calls: number;
  config: Record<string, string>;
}
interface Overview {
  providers: Provider[];
  connections: Connection[];
  nango_enabled: boolean;
}
interface Activity {
  id: string;
  kind: string;
  status: "ok" | "error";
  message: string;
  created_at: string;
}

const BRAND: Record<string, string> = {
  followupboss: "bg-[#1f6feb]", close: "bg-[#2f3e4e]", hubspot: "bg-[#ff7a59]", highlevel: "bg-[#188bf6]",
  pipedrive: "bg-[#1a1a1a]", salesforce: "bg-[#00a1e0]", zoho: "bg-[#e42527]", attio: "bg-[#0f0f0f]",
  google_sheets: "bg-[#0f9d58]", slack: "bg-[#4a154b]",
};

const DOMAIN: Record<string, string> = {
  followupboss: "followupboss.com", close: "close.com", hubspot: "hubspot.com", highlevel: "gohighlevel.com",
  pipedrive: "pipedrive.com", salesforce: "salesforce.com", zoho: "zoho.com", attio: "attio.com",
  google_sheets: "sheets.google.com", slack: "slack.com",
};

function Logo({ p }: { p: Provider }) {
  const [failed, setFailed] = useState(false);
  const initials = p.name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const domain = DOMAIN[p.key];
  if (domain && !failed) {
    return (
      <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-white ring-1 ring-zinc-200/80">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`} alt="" className="h-6 w-6" onError={() => setFailed(true)} />
      </span>
    );
  }
  return (
    <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-xs font-bold text-white", BRAND[p.key] ?? "bg-zinc-700")}>
      {initials}
    </span>
  );
}

/** Rounded grouped list with dividers inset past the logo (iOS settings style). */
function Group({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div>
      {title && <div className="mb-2 px-1 text-xs font-medium uppercase tracking-wide text-zinc-500">{title}</div>}
      <ul className="overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 [&>li+li]:before:absolute [&>li+li]:before:left-[68px] [&>li+li]:before:right-4 [&>li+li]:before:top-0 [&>li+li]:before:h-px [&>li+li]:before:bg-zinc-100">
        {children}
      </ul>
    </div>
  );
}

const errText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function CrmIntegrations() {
  const { data, error, mutate } = useSWR<Overview>("/api/integrations/crm", fetcher);
  const { data: agents } = useSWR<{ id: string; name: string }[]>("/api/agents/", fetcher);
  const [connecting, setConnecting] = useState<Provider | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  if (error) return <Notice tone="red">Couldn&apos;t load CRM integrations: {error.message}</Notice>;
  if (!data) {
    return (
      <Card className="flex justify-center p-10">
        <Spinner />
      </Card>
    );
  }
  const byKey = Object.fromEntries(data.connections.map((c) => [c.provider, c]));
  const connected = data.providers.filter((p) => byKey[p.key]);
  const available = data.providers.filter((p) => !byKey[p.key]);

  return (
    <Card>
      <CardHeader
        title="CRM & apps"
        description="Every AI call is logged in your CRM with the summary, outcome and recording link. Import contacts to call, and have an agent call new leads within a minute."
      />
      <div className="space-y-6 p-3 sm:p-5">
        {connected.length > 0 && (
          <Group title="Connected">
            {connected.map((p) => (
              <ConnectedRow
                key={p.key}
                p={p}
                c={byKey[p.key]}
                agents={agents ?? []}
                open={open === p.key}
                onToggle={() => setOpen(open === p.key ? null : p.key)}
                onChange={() => void mutate()}
                onReconnect={() => setConnecting(p)}
              />
            ))}
          </Group>
        )}
        <Group title={connected.length ? "Available" : undefined}>
          {available.map((p) => {
            const ready = p.native || p.oauth;
            return (
              <li key={p.key} className="relative">
                <button
                  type="button"
                  disabled={!ready}
                  onClick={() => setConnecting(p)}
                  className="group flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors hover:bg-zinc-50 disabled:cursor-default disabled:hover:bg-transparent"
                >
                  <Logo p={p} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] font-medium text-zinc-900">{p.name}</span>
                    <span className="block truncate text-xs text-zinc-500">{p.description}</span>
                  </span>
                  {ready ? (
                    <span className="flex shrink-0 items-center gap-1.5 text-sm text-zinc-500 transition-colors group-hover:text-brand-600">
                      Connect <ExternalLink className="h-4 w-4" />
                    </span>
                  ) : (
                    <span className="shrink-0 text-sm text-zinc-400">Coming soon</span>
                  )}
                </button>
              </li>
            );
          })}
        </Group>
      </div>
      {connecting && (
        <ConnectModal
          p={connecting}
          existing={byKey[connecting.key]}
          onClose={() => setConnecting(null)}
          onDone={() => {
            setOpen(connecting.key);
            setConnecting(null);
            void mutate();
          }}
        />
      )}
    </Card>
  );
}

function ConnectModal({ p, existing, onClose, onDone }: { p: Provider; existing?: Connection; onClose: () => void; onDone: () => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => ({ ...(existing?.config ?? {}) }));
  const [busy, setBusy] = useState<"key" | "oauth" | null>(null);
  const [err, setErr] = useState("");
  const configFields = p.fields.filter((f) => !f.secret);
  const secretFields = p.fields.filter((f) => f.secret);

  const connectKey = async () => {
    setBusy("key");
    setErr("");
    try {
      await post(`/api/integrations/crm/${p.key}/connect`, { fields: values });
      onDone();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(null);
    }
  };

  const connectOAuth = async () => {
    setBusy("oauth");
    setErr("");
    try {
      const { token } = await post<{ token: string }>(`/api/integrations/crm/${p.key}/oauth/session`);
      const { default: Nango } = await import("@nangohq/frontend");
      const ui = new Nango().openConnectUI({
        sessionToken: token,
        onEvent: async (event) => {
          if (event.type === "connect") {
            try {
              await post(`/api/integrations/crm/${p.key}/oauth/complete`, { connection_id: event.payload.connectionId, fields: values });
              ui.close();
              onDone();
            } catch (e) {
              setErr(errText(e));
            }
          }
          if (event.type === "close") setBusy(null);
        },
      });
    } catch (e) {
      setErr(errText(e));
      setBusy(null);
    }
  };

  return (
    <Modal open onClose={onClose} title={`Connect ${p.name}`}>
      <div className="space-y-4">
        <p className="text-sm text-zinc-600">{p.description}</p>
        {configFields.map((f) => (
          <Field key={f.name} label={f.label} hint={f.help}>
            <Input value={values[f.name] ?? ""} placeholder={f.placeholder} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
          </Field>
        ))}
        {p.oauth && (
          <Button variant="primary" className="w-full justify-center" loading={busy === "oauth"} onClick={() => void connectOAuth()}>
            Connect with {p.name}
          </Button>
        )}
        {p.native && (
          <>
            {p.oauth && <div className="text-center text-xs text-zinc-400">or paste an API key</div>}
            {secretFields.map((f) => (
              <Field key={f.name} label={f.label} hint={f.help}>
                <Input
                  type="password"
                  autoComplete="off"
                  value={values[f.name] ?? ""}
                  placeholder={existing?.method === "api_key" ? "Leave blank to keep the saved key" : f.placeholder}
                  onChange={(e) => setValues({ ...values, [f.name]: e.target.value.trim() })}
                />
              </Field>
            ))}
            <Button variant={p.oauth ? "secondary" : "primary"} className="w-full justify-center" loading={busy === "key"} onClick={() => void connectKey()}>
              Connect
            </Button>
          </>
        )}
        {err && <Notice tone="red">{err}</Notice>}
        <p className="text-xs text-zinc-400">
          Keys are encrypted and never shown again.
          {p.docs_url && (
            <>
              {" "}
              <a href={p.docs_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-brand-600 hover:underline">
                {p.name} docs <ExternalLink className="h-3 w-3" />
              </a>
            </>
          )}
        </p>
      </div>
    </Modal>
  );
}

function ConnectedRow({
  p, c, agents, open, onToggle, onChange, onReconnect,
}: {
  p: Provider; c: Connection; agents: { id: string; name: string }[]; open: boolean;
  onToggle: () => void; onChange: () => void; onReconnect: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const { data: activity, mutate: refreshActivity } = useSWR<{ items: Activity[] }>(open ? `/api/integrations/crm/${p.key}/activity` : null, fetcher);

  const run = async (name: string, fn: () => Promise<unknown>, ok?: (r: unknown) => string) => {
    setBusy(name);
    setMsg(null);
    try {
      const r = await fn();
      if (ok) setMsg({ tone: "green", text: ok(r) });
      onChange();
      void refreshActivity();
    } catch (e) {
      setMsg({ tone: "red", text: errText(e) });
    } finally {
      setBusy(null);
    }
  };
  const save = (body: Record<string, unknown>) => run("settings", () => patch(`/api/integrations/crm/${p.key}`, body));
  const s = c.settings;

  return (
    <li className="relative">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors hover:bg-zinc-50">
        <Logo p={p} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-[15px] font-medium text-zinc-900">
            {p.name}
            {s.speed_to_lead_agent_id && (
              <Badge tone="brand">
                <Zap className="h-3 w-3" /> Speed to lead
              </Badge>
            )}
          </div>
          <div className="truncate text-xs text-zinc-500">
            {c.account_label}
            {c.last_synced_at ? ` · last sync ${timeAgo(c.last_synced_at)}` : ""}
          </div>
        </div>
        {c.status === "connected" ? (
          <span className="flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Connected</span>
          </span>
        ) : (
          <span className="shrink-0 rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700">Needs attention</span>
        )}
        <ChevronRight className={cn("h-5 w-5 shrink-0 text-zinc-400 transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="space-y-5 border-t border-zinc-100 bg-zinc-50/50 p-4 sm:pl-[68px]">
          {c.status === "error" && c.last_error && <Notice tone="red">{c.last_error}</Notice>}
          <div className="grid gap-3 md:grid-cols-2">
            <Toggle
              checked={s.log_calls}
              onChange={(v) => void save({ log_calls: v })}
              label={p.category === "notify" ? "Post every finished call" : p.category === "sheet" ? "Add a row for every call" : "Log every call"}
              description={p.category === "crm" ? "Adds the call, summary, outcome and recording link to the contact." : undefined}
            />
            {p.category === "crm" && (
              <Toggle
                checked={s.create_contacts}
                onChange={(v) => void save({ create_contacts: v })}
                label="Create missing contacts"
                description={`If the number isn't in ${p.name} yet, add it.`}
              />
            )}
            <Toggle
              checked={s.only_connected}
              onChange={(v) => void save({ only_connected: v })}
              label="Only answered calls"
              description="Skip no-answers and failed calls."
            />
          </div>

          {p.can_new_leads && (
            <div className="rounded-xl bg-brand-50/50 p-4 ring-1 ring-brand-100">
              <div className="flex items-center gap-2 text-sm font-medium text-zinc-900">
                <Zap className="h-4 w-4 text-brand-600" /> Speed to lead
              </div>
              <p className="mt-1 text-xs text-zinc-600">
                When a new lead lands in {p.name}, this agent calls them within about a minute (8 AM – 9 PM in your account&apos;s time zone; later leads are
                called when the window opens). Uses calling credits.
              </p>
              <Select
                className="mt-3"
                value={s.speed_to_lead_agent_id ?? ""}
                onChange={(e) => void save({ speed_to_lead_agent_id: e.target.value })}
                aria-label="Speed to lead agent"
              >
                <option value="">Off</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    Call with {a.name}
                  </option>
                ))}
              </Select>
              {c.pending_calls > 0 && <p className="mt-2 text-xs text-zinc-600">{c.pending_calls} new lead(s) waiting for calling hours.</p>}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {p.can_import && (
              <Button
                size="sm"
                loading={busy === "import"}
                onClick={() =>
                  void run(
                    "import",
                    () => post<{ created: number; linked: number; found: number }>(`/api/integrations/crm/${p.key}/import`),
                    (r) => {
                      const x = r as { created: number; linked: number; found: number };
                      return `Imported ${x.created} new contact${x.created === 1 ? "" : "s"} (${x.found} with phone numbers found).`;
                    },
                  )
                }
              >
                <Download className="h-3.5 w-3.5" /> Import contacts
              </Button>
            )}
            <Button size="sm" loading={busy === "test"} onClick={() => void run("test", () => post(`/api/integrations/crm/${p.key}/test`), () => "Test finished — see activity below.")}>
              <RefreshCw className="h-3.5 w-3.5" /> Test connection
            </Button>
            <Button size="sm" variant="ghost" onClick={onReconnect}>
              Update credentials
            </Button>
            <Button
              size="sm"
              variant="danger"
              loading={busy === "delete"}
              onClick={() => {
                if (window.confirm(`Disconnect ${p.name}? Calls will stop syncing.`)) void run("delete", () => del(`/api/integrations/crm/${p.key}`));
              }}
            >
              <Trash2 className="h-3.5 w-3.5" /> Disconnect
            </Button>
          </div>
          {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}

          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Activity</div>
            {!activity ? (
              <Spinner />
            ) : activity.items.length === 0 ? (
              <p className="text-sm text-zinc-500">Nothing yet — finished calls will show up here.</p>
            ) : (
              <ul className="divide-y divide-zinc-100 text-sm">
                {activity.items.slice(0, 12).map((a) => (
                  <li key={a.id} className="flex items-start gap-2 py-2">
                    <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", a.status === "ok" ? "bg-emerald-500" : "bg-red-500")} />
                    <span className="min-w-0 flex-1 text-zinc-700">{a.message}</span>
                    <span className="shrink-0 text-xs text-zinc-400">{timeAgo(a.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </li>
  );
}
