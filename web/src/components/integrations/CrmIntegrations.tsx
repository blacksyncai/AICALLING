"use client";

import { CheckCircle2, ChevronRight, ExternalLink, Puzzle, Zap } from "lucide-react";
import type React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import MatteAlertFeedback from "@/components/ui/matte-alert-feedback";
import { AssistantRows } from "./AssistantRows";
import { Badge, Button, Card, CardHeader, Field, Input, Modal, Notice, Select, Spinner, Toggle } from "@/components/ui";
import { del, fetcher, post, put } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";

export interface ProviderField {
  name: string;
  label: string;
  secret: boolean;
  placeholder: string;
  help: string;
}
export interface Provider {
  key: string;
  name: string;
  category: "crm" | "notify" | "sheet";
  description: string;
  native: boolean;
  setup_required_reason?: string;
  oauth: boolean;
  /** Our own OAuth sign-in (no Nango): the browser goes to the CRM's login page and comes back connected. */
  oauth_native?: boolean;
  can_import: boolean;
  can_new_leads: boolean;
  docs_url: string;
  /** "opportunity" / "deal" / "stage" when the CRM has pipelines to sync; "" otherwise. */
  pipeline_noun: string;
  can_install: boolean;
  install_style: "pipeline" | "tags";
  can_activity: boolean;
  can_map_fields?: boolean;
  fields: ProviderField[];
}
export interface AutoRule {
  id: string;
  name: string;
  filters: Record<string, string[]>;
  skip_contacted: boolean;
  campaign_id: string | null;
  list_tag: string;
  every_minutes: number;
  enabled: boolean;
  last_run_at: string | null;
  last_result: { ok: boolean; created?: number; added?: number; error?: string } | null;
  runs: number;
  summary: string;
}
export interface Connection {
  provider: string;
  method: "api_key" | "nango";
  account_label: string;
  status: "connected" | "error";
  last_error: string | null;
  last_synced_at: string | null;
  settings: {
    log_calls: boolean; create_contacts: boolean; csv_create_fields?: boolean; only_connected: boolean; speed_to_lead_agent_id: string | null;
    activity_agent_id: string | null;
    min_seconds: number;
    skip_outcomes: string[];
    only_outcomes: string[];
    only_sentiments: string[];
    note_summary: boolean;
    note_details: boolean;
    note_link: boolean;
    note_transcript?: boolean;
  };
  auto_imports: AutoRule[];
  pending_calls: number;
  config: Record<string, string>;
  pipeline: { id: string; name: string; mapped: number } | null;
  installs: {
    agent_id: string; agent_name: string; pipeline_id: string; pipeline_name: string; stages: string[];
    retry: { max_tries: number; after_hours: number; voicemail: boolean };
  }[];
}
interface Overview {
  providers: Provider[];
  connections: Connection[];
  nango_enabled: boolean;
}
export interface Activity {
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
  google_sheets: "sheets.google.com", slack: "slack.com", boldtrail: "kvcore.com", lofty: "lofty.com",
  sierra: "sierrainteractive.com", oracle_sales: "oracle.com", realgeeks: "realgeeks.com", boomtown: "boomtownroi.com", brivity: "brivity.com",
};

export function Logo({ p }: { p: Provider }) {
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

// Native connectors on the roadmap (shown as "coming soon" next to the ones the API lists as not ready yet).
const UPCOMING = [
  { key: "monday", name: "Monday.com", domain: "monday.com", description: "Log AI calls on items and import contacts from boards." },
  { key: "calendly", name: "Calendly", domain: "calendly.com", description: "Book meetings straight into your Calendly event types." },
];

function SoonLogo({ name, domain }: { name: string; domain?: string }) {
  const [failed, setFailed] = useState(false);
  if (domain && !failed) {
    return (
      <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-white opacity-70 ring-1 ring-zinc-200/80 grayscale-[40%]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`} alt="" className="h-6 w-6" onError={() => setFailed(true)} />
      </span>
    );
  }
  return <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-zinc-200 text-xs font-bold text-zinc-600">{name[0]}</span>;
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

export const errText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function CrmIntegrations() {
  const { data, error, mutate } = useSWR<Overview>("/api/integrations/crm", fetcher);
  const [connecting, setConnecting] = useState<Provider | null>(null);
  const router = useRouter();

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
  const pushing = connected.filter((p) => byKey[p.key]?.settings?.log_calls);

  const live = available.filter((p) => p.native || p.oauth || p.oauth_native);
  const soon = available.filter((p) => !(p.native || p.oauth || p.oauth_native));

  return (
    <Card className="overflow-hidden">
      {/* Header: a "plugin store" feel — live count, what a connector does. */}
      <div className="relative overflow-hidden border-b border-zinc-100 bg-gradient-to-br from-zinc-950 via-zinc-900 to-[#2a1408] px-5 py-6 text-white sm:px-7">
        <div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-brand-500/25 blur-3xl" />
        <div className="relative flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-brand-300">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              Live connectors
            </div>
            <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">Plug BlackSync into the tools you already use</h2>
            <p className="mt-1.5 text-sm text-zinc-300">
              Every AI call lands in your CRM with the summary, outcome and recording. Import contacts to call, and have an agent
              ring new leads within a minute.
            </p>
          </div>
          <div className="flex gap-2 text-xs">
            <span className="rounded-full bg-white/10 px-3 py-1 font-medium ring-1 ring-white/15">{live.length + connected.length} live</span>
            {connected.length > 0 && (
              <span className="rounded-full bg-emerald-400/15 px-3 py-1 font-medium text-emerald-300 ring-1 ring-emerald-400/30">{connected.length} connected</span>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-6 p-3 sm:p-5">
        {pushing.length > 0 && (
          <MatteAlertFeedback
            cardTitle="Live CRM sync"
            pillText={pushing.length === 1 ? "1 CRM" : `${pushing.length} CRMs`}
            cardDescription={`Every AI call — test calls included — is logged in ${pushing.map((p) => p.name).join(" and ")}.`}
            alertTitle="Test calls show up in your CRM too"
            alertDetail="Turn off “Log every call” on a connection while testing, or disconnect it to stop syncing completely."
            showControls={false}
            persistKey={`crm-sync-${pushing.map((p) => p.key).join("-")}`}
          />
        )}
        {connected.length > 0 && (
          <Group title="Connected">
            {connected.map((p) => (
              <ConnectedRow key={p.key} p={p} c={byKey[p.key]} />
            ))}
          </Group>
        )}

        {live.length > 0 && (
          <Group title={connected.length ? "Add another" : "Connect in a click"}>
            {live.map((p) => (
              <li key={p.key} className="relative">
                <button
                  type="button"
                  onClick={() => setConnecting(p)}
                  className="group flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors hover:bg-zinc-50"
                >
                  <Logo p={p} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="text-[15px] font-medium text-zinc-900">{p.name}</span>
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-1.5 py-px text-[10px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Live
                      </span>
                    </span>
                    <span className="block truncate text-xs text-zinc-500">{p.description}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5 text-sm text-zinc-500 transition-colors group-hover:text-brand-600">
                    Connect <ExternalLink className="h-4 w-4" />
                  </span>
                </button>
              </li>
            ))}
          </Group>
        )}

        <AssistantRows />

        {/* Don't see yours: API + webhooks, and our team can wire it up. */}
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-brand-50 via-orange-50 to-amber-50 p-5 ring-1 ring-brand-200/70">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3.5">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-brand-600 shadow-sm ring-1 ring-brand-200">
                <Puzzle className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <div className="text-[15px] font-semibold text-zinc-900">Don&apos;t see your CRM? Don&apos;t worry.</div>
                <p className="mt-0.5 max-w-xl text-sm text-zinc-600">
                  BlackSync has a native API and webhooks that connect to almost anything — and our team can set it up for you.
                </p>
              </div>
            </div>
            <Link
              href="/agents/expert"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-zinc-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-600"
            >
              Have our team set it up <ChevronRight className="h-4 w-4" />
            </Link>
          </div>
        </div>

        <Group title="Coming soon">
          {[...soon.map((p) => ({ key: p.key, name: p.name, description: p.description, domain: DOMAIN[p.key], pending: !!p.setup_required_reason })), ...UPCOMING.map((p) => ({ ...p, pending: false }))].map((x) => (
            <li key={x.key} className="relative flex items-center gap-4 px-4 py-3.5">
              <SoonLogo name={x.name} domain={x.domain} />
              <span className="min-w-0 flex-1">
                <span className="block text-[15px] font-medium text-zinc-700">{x.name}</span>
                <span className="block truncate text-xs text-zinc-500">{x.description}</span>
              </span>
              <span className="shrink-0 rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-semibold text-zinc-500">{x.pending ? "API verification pending" : "Coming soon"}</span>
            </li>
          ))}
        </Group>
      </div>
      {connecting && (
        <ConnectModal
          p={connecting}
          existing={byKey[connecting.key]}
          onClose={() => setConnecting(null)}
          onDone={() => {
            router.push(`/integrations/${connecting.key}`);
            setConnecting(null);
            void mutate();
          }}
        />
      )}
    </Card>
  );
}

export function ConnectModal({ p, existing, onClose, onDone }: { p: Provider; existing?: Connection; onClose: () => void; onDone: () => void }) {
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

  const [sandbox, setSandbox] = useState(false);
  const connectNative = async () => {
    setBusy("oauth");
    setErr("");
    try {
      const { url } = await post<{ url: string }>(`/api/integrations/crm/${p.key}/oauth/start`, { sandbox });
      window.location.href = url; // stays busy while the browser goes to the sign-in page
    } catch (e) {
      setErr(errText(e));
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
        {p.oauth_native ? (
          <>
            <Button variant="primary" className="w-full justify-center" loading={busy === "oauth"} onClick={() => void connectNative()}>
              Connect with {p.name}
            </Button>
            <label className="flex items-center gap-2 text-xs text-zinc-500">
              <input type="checkbox" checked={sandbox} onChange={(e) => setSandbox(e.target.checked)} className="accent-brand-600" />
              It&apos;s a sandbox org (test.salesforce.com)
            </label>
          </>
        ) : (
          p.oauth && (
            <Button variant="primary" className="w-full justify-center" loading={busy === "oauth"} onClick={() => void connectOAuth()}>
              Connect with {p.name}
            </Button>
          )
        )}
        {p.native && (
          <>
            {(p.oauth || p.oauth_native) && <div className="text-center text-xs text-zinc-400">or paste your credentials</div>}
            {secretFields.map((f) => (
              <Field key={f.name} label={f.label} hint={f.help}>
                <Input
                  type="password"
                  autoComplete="off"
                  value={values[f.name] ?? ""}
                  placeholder={existing?.method === "api_key" ? "Leave blank to keep the saved key" : f.placeholder}
                  onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                />
              </Field>
            ))}
            <Button variant={p.oauth || p.oauth_native ? "secondary" : "primary"} className="w-full justify-center" loading={busy === "key"} onClick={() => void connectKey()}>
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

function ConnectedRow({ p, c }: { p: Provider; c: Connection }) {
  const s = c.settings;
  const rules = c.auto_imports.filter((r) => r.enabled).length;
  return (
    <li className="relative">
      <Link href={`/integrations/${p.key}`} className="flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors hover:bg-zinc-50">
        <Logo p={p} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-[15px] font-medium text-zinc-900">
            {p.name}
            {s.speed_to_lead_agent_id && (
              <Badge tone="brand">
                <Zap className="h-3 w-3" /> Speed to lead
              </Badge>
            )}
            {rules > 0 && <Badge tone="gray">{rules} auto-sync</Badge>}
            {c.pipeline && <Badge tone="gray">Stages synced</Badge>}
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
        <span className="hidden shrink-0 text-sm text-zinc-500 sm:inline">Set up</span>
        <ChevronRight className="h-5 w-5 shrink-0 text-zinc-400" />
      </Link>
    </li>
  );
}

interface PipelineInfo {
  supported: boolean;
  noun: string;
  pipelines: { id: string; name: string; stages: { id: string; label: string; kind: string }[] }[];
  suggested: Record<string, Record<string, string>>;
  outcomes: { key: string; label: string }[];
  current: { id: string; map: Record<string, string>; create: boolean; forward_only: boolean } | null;
}

/** Pick a pipeline and map each call result to a stage; calls then move the contact's deal there. */
export function PipelineSync({ p, c, onSaved }: { p: Provider; c: Connection; onSaved: () => void }) {
  const { data, error, mutate } = useSWR<PipelineInfo>(`/api/integrations/crm/${p.key}/pipelines`, fetcher, { revalidateOnFocus: false });
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [map, setMap] = useState<Record<string, string> | null>(null);
  const [create, setCreate] = useState<boolean | null>(null);
  const [forward, setForward] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);

  if (error) return <Notice tone="red">Couldn&apos;t load {p.name} pipelines: {(error as Error).message}</Notice>;
  if (!data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-zinc-200 bg-white p-4 text-sm text-zinc-500">
        <Spinner /> Reading your {p.name} pipelines…
      </div>
    );
  }
  if (!data.supported) return null;

  const noun = data.noun === "stage" ? "lead stage" : data.noun;
  const pid = pipelineId ?? data.current?.id ?? "";
  const pipe = data.pipelines.find((x) => x.id === pid);
  const currentMap = map ?? (data.current && data.current.id === pid ? data.current.map : data.suggested[pid] ?? {});
  const doCreate = create ?? data.current?.create ?? true;
  const fwd = forward ?? data.current?.forward_only ?? true;
  const dirty = pipelineId !== null || map !== null || create !== null || forward !== null;

  const choosePipeline = (id: string) => {
    setPipelineId(id);
    setMap(id ? { ...(data.suggested[id] ?? {}) } : {});
    setMsg(null);
  };
  const save = async (off = false) => {
    setSaving(true);
    setMsg(null);
    try {
      await put(`/api/integrations/crm/${p.key}/pipelines`, off ? { pipeline_id: "" } : { pipeline_id: pid, map: currentMap, create: doCreate, forward_only: fwd });
      setPipelineId(null);
      setMap(null);
      setCreate(null);
      setForward(null);
      await mutate();
      onSaved();
      setMsg({ tone: "green", text: off ? "Pipeline sync is off." : `Saved — calls now move ${noun}s in ${pipe?.name ?? "this pipeline"}.` });
    } catch (e) {
      setMsg({ tone: "red", text: errText(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 rounded-xl border border-zinc-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-zinc-900">Pipeline sync</div>
          <p className="mt-0.5 text-xs text-zinc-500">
            After every call, move the contact&apos;s {noun} to the stage that matches the result. We pre-filled the matches from your stage names.
          </p>
        </div>
        {c.pipeline && !dirty && <Badge tone="green">On · {c.pipeline.name}</Badge>}
      </div>
      <Field label="Pipeline">
        <Select value={pid} onChange={(e) => choosePipeline(e.target.value)}>
          <option value="">Off — don&apos;t move {noun}s</option>
          {data.pipelines.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name} · {x.stages.length} stages
            </option>
          ))}
        </Select>
      </Field>
      {pipe && (
        <>
          <div className="divide-y divide-zinc-100 rounded-lg ring-1 ring-zinc-100">
            {data.outcomes.map((o) => (
              <div key={o.key} className="flex flex-col gap-1.5 px-3 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
                <span className="text-sm text-zinc-700">{o.label}</span>
                <Select
                  className="sm:w-60"
                  value={currentMap[o.key] ?? ""}
                  onChange={(e) => {
                    const next = { ...currentMap };
                    if (e.target.value) next[o.key] = e.target.value;
                    else delete next[o.key];
                    setMap(next);
                  }}
                  aria-label={`Stage for ${o.label}`}
                >
                  <option value="">Don&apos;t move</option>
                  {pipe.stages.map((st) => (
                    <option key={st.id} value={st.id}>
                      {st.label}
                      {st.kind !== "active" ? ` (${st.kind})` : ""}
                    </option>
                  ))}
                </Select>
              </div>
            ))}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {data.noun !== "stage" && (
              <Toggle
                checked={doCreate}
                onChange={setCreate}
                label={`Create the ${noun} if they don't have one`}
                description={`Adds a new ${noun} in ${pipe.name} at the mapped stage.`}
              />
            )}
            <Toggle checked={fwd} onChange={setForward} label="Only move forward" description="Never move a deal back to an earlier stage, or touch won/lost ones." />
          </div>
        </>
      )}
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <div className="flex flex-wrap justify-end gap-2">
        {c.pipeline && (
          <Button size="sm" variant="ghost" disabled={saving} onClick={() => void save(true)}>
            Turn off
          </Button>
        )}
        <Button size="sm" variant="primary" loading={saving} disabled={!pid || (!dirty && !!c.pipeline)} onClick={() => void save()}>
          {c.pipeline ? "Save mapping" : "Turn on pipeline sync"}
        </Button>
      </div>
    </div>
  );
}

/** "BlackSync AI · <agent>" pipelines inside the CRM: drag a card into the queue stage and the agent calls. */
export function BlackSyncPipelines({
  p, c, agents, onChange,
}: {
  p: Provider; c: Connection; agents: { id: string; name: string }[]; onChange: () => void;
}) {
  const [wizard, setWizard] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const installed = new Set(c.installs.map((i) => i.agent_id));
  const free = agents.filter((a) => !installed.has(a.id));
  const tags = p.install_style === "tags";

  const remove = async (id: string) => {
    setBusy(id);
    try {
      await del(`/api/integrations/crm/${p.key}/install/${id}`);
      onChange();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4 rounded-xl bg-zinc-950 p-4 text-white ring-1 ring-white/10 bg-[radial-gradient(420px_200px_at_0%_0%,rgba(249,115,22,0.18),transparent_70%)]">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Zap className="h-4 w-4 text-brand-400" /> Call straight from {tags ? `${p.name} tags` : `your ${p.name} pipeline`}
        </div>
        {tags ? (
          <p className="mt-1 text-xs leading-relaxed text-zinc-400">
            Pick an agent and you get a tag like <span className="text-zinc-200">AI Call - Synchro</span>. Tag anyone in {p.name} — one person or a
            whole smart list — and the agent calls them within a minute, already knowing their stage, notes, calls and the homes they viewed. The
            tag then flips to the result (<span className="text-zinc-200">AI Booked, AI Voicemail, AI Talked…</span>) so you can build smart
            lists on it, and the person&apos;s agent gets a task for callbacks and booked meetings. No answers are retried up to 3 times.
          </p>
        ) : (
          <p className="mt-1 text-xs leading-relaxed text-zinc-400">
            We create a <span className="text-zinc-200">BlackSync AI</span> pipeline in {p.name} for an agent. Drag any lead into
            {" "}<span className="text-zinc-200">Queued for AI call</span> and the agent calls them within a minute, already knowing their notes and
            history. The card then moves itself: Voicemail left, Talked, Meeting booked… No answers are retried up to 3 times.
          </p>
        )}
      </div>

      {c.installs.map((i) => (
        <div key={i.agent_id} className="rounded-lg bg-white/[0.04] p-3 ring-1 ring-white/10">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{i.pipeline_name}</div>
              <div className="text-xs text-zinc-400">
                Calls with {i.agent_name} · retries no-answers{i.retry.voicemail ? " and voicemails" : ""} up to {i.retry.max_tries}× every {i.retry.after_hours}h
              </div>
            </div>
            <button
              type="button"
              onClick={() => void remove(i.agent_id)}
              disabled={busy === i.agent_id}
              className="shrink-0 rounded-md px-2 py-1 text-xs text-zinc-400 hover:bg-white/10 hover:text-white"
            >
              Stop watching
            </button>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1">
            {i.stages.map((st, n) => (
              <span key={st} className="flex items-center gap-1 text-[11px]">
                <span className={cn("rounded-full px-2 py-0.5", n === 0 ? "bg-brand-500 text-white" : "bg-white/[0.06] text-zinc-300")}>{st}</span>
                {n < i.stages.length - 1 && <span className="text-zinc-600">›</span>}
              </span>
            ))}
          </div>
        </div>
      ))}

      {free.length > 0 && (
        <Button variant="primary" onClick={() => setWizard(true)}>
          <Zap className="h-4 w-4" /> {c.installs.length ? "Add another AI calling " + (tags ? "tag set" : "pipeline") : tags ? `Set up AI calling tags in ${p.name}` : `Create an AI calling pipeline in ${p.name}`}
        </Button>
      )}
      {wizard && (
        <div className="text-zinc-900">
        <InstallWizard
          p={p}
          agents={free}
          onClose={() => setWizard(false)}
          onDone={(text) => {
            setWizard(false);
            setMsg({ tone: "green", text });
            onChange();
          }}
        />
        </div>
      )}
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
    </div>
  );
}

interface InstallPreview {
  supported: boolean;
  style: "pipeline" | "tags";
  noun: string;
  stages: { key: string; label: string; kind: string; what: string }[];
}

/** Preview the AI calling pipeline (or tags) BlackSync will create in the CRM, tweak it, then allow it. */
function InstallWizard({ p, agents, onClose, onDone }: { p: Provider; agents: { id: string; name: string }[]; onClose: () => void; onDone: (msg: string) => void }) {
  const { data: preview, error } = useSWR<InstallPreview>(`/api/integrations/crm/${p.key}/install/preview`, fetcher);
  const [agentId, setAgentId] = useState(agents[0]?.id ?? "");
  const agentName = agents.find((a) => a.id === agentId)?.name ?? "Agent";
  const [name, setName] = useState("");
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [tries, setTries] = useState(3);
  const [hours, setHours] = useState(4);
  const [retryVm, setRetryVm] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const tags = p.install_style === "tags";
  const defaultName = tags ? agentName : `BlackSync AI calling · ${agentName}`;

  const allow = async () => {
    setBusy(true);
    setErr("");
    try {
      await post(`/api/integrations/crm/${p.key}/install`, {
        agent_id: agentId, name: name.trim() || defaultName, labels: Object.fromEntries(Object.entries(labels).filter(([, v]) => v.trim())),
        max_tries: tries, retry_hours: hours, retry_voicemail: retryVm,
      });
      const first = labels.queued?.trim() || (tags ? `AI Call - ${name.trim() || agentName}` : preview?.stages[0]?.label);
      onDone(
        tags
          ? `Done — in ${p.name}, add the tag “${first}” to anyone (or bulk-tag a smart list) and ${agentName} calls them.`
          : `Done — open ${p.name}, find “${name.trim() || defaultName}” and move anyone into “${first}”. ${agentName} calls them within a minute.`,
      );
    } catch (e) {
      setErr(errText(e));
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={tags ? `AI calling tags in ${p.name}` : `Create an AI calling pipeline in ${p.name}`} wide>
      {error ? (
        <Notice tone="red">{errText(error)}</Notice>
      ) : !preview ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <div className="space-y-5">
          <p className="text-sm text-zinc-600">
            {tags
              ? `BlackSync will use these tags in ${p.name}. Tag anyone with the first one and the agent calls them; the tag then flips to the result.`
              : `BlackSync will create this pipeline in ${p.name}. Move anyone into the first stage and the agent calls them — then the card moves itself through the stages below.`}{" "}
            Rename anything you like before you allow it.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Agent that calls">
              <Select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={tags ? "Name used in the tags" : "Pipeline name"}>
              <Input value={name} maxLength={60} placeholder={tags ? agentName : `e.g. BlackSync AI calling — Expired`} onChange={(e) => setName(e.target.value)} />
            </Field>
          </div>

          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">{tags ? "Tags" : "Stages"} — what happens in each</div>
            <ol className="divide-y divide-zinc-100 rounded-xl ring-1 ring-zinc-200">
              {preview.stages.map((st, i) => (
                <li key={st.key} className="grid gap-2 px-3 py-2.5 sm:grid-cols-[28px_220px_minmax(0,1fr)] sm:items-center">
                  <span className={cn("flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold", i === 0 ? "bg-brand-600 text-white" : "bg-zinc-100 text-zinc-600")}>{i + 1}</span>
                  <Input
                    value={labels[st.key] ?? ""}
                    placeholder={tags && st.key === "queued" ? `AI Call - ${name.trim() || agentName}` : st.label}
                    maxLength={60}
                    onChange={(e) => setLabels({ ...labels, [st.key]: e.target.value })}
                    className="h-8 text-sm"
                    aria-label={`Name for ${st.label}`}
                  />
                  <span className="text-xs text-zinc-500">
                    {st.kind === "lost" && <Badge tone="gray">closed</Badge>} {st.what}
                  </span>
                </li>
              ))}
            </ol>
          </div>

          <div className="rounded-xl bg-zinc-50 p-4 ring-1 ring-zinc-100">
            <div className="text-sm font-medium text-zinc-900">Call back people who don&apos;t pick up</div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-zinc-700">
              Try up to
              <span className="inline-block w-20">
              <Select value={String(tries)} onChange={(e) => setTries(Number(e.target.value))}>
                {[1, 2, 3, 4, 5, 6].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </Select>
              </span>
              times, waiting
              <span className="inline-block w-32">
              <Select value={String(hours)} onChange={(e) => setHours(Number(e.target.value))}>
                {[1, 2, 4, 8, 24, 48].map((n) => (
                  <option key={n} value={n}>
                    {n < 24 ? `${n} hour${n > 1 ? "s" : ""}` : `${n / 24} day${n > 24 ? "s" : ""}`}
                  </option>
                ))}
              </Select>
              </span>
              between calls.
            </div>
            <div className="mt-3">
              <Toggle checked={retryVm} onChange={setRetryVm} label="Retry voicemails too" description="Off = only no-answers get another call." />
            </div>
          </div>

          {err && <Notice tone="red">{err}</Notice>}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4">
            <p className="text-xs text-zinc-500">Nothing in {p.name} changes until you allow it. Existing {tags ? "tags" : "pipelines"} with the same names are reused, not duplicated.</p>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button variant="primary" loading={busy} disabled={!agentId} onClick={() => void allow()}>
                Allow &amp; create in {p.name}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
