"use client";

import { CheckCircle2, ChevronRight, ExternalLink, Zap } from "lucide-react";
import type React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import MatteAlertFeedback from "@/components/ui/matte-alert-feedback";
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
  oauth: boolean;
  can_import: boolean;
  can_new_leads: boolean;
  docs_url: string;
  /** "opportunity" / "deal" / "stage" when the CRM has pipelines to sync; "" otherwise. */
  pipeline_noun: string;
  can_install: boolean;
  install_style: "pipeline" | "tags";
  can_activity: boolean;
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
    log_calls: boolean; create_contacts: boolean; only_connected: boolean; speed_to_lead_agent_id: string | null;
    activity_agent_id: string | null;
    min_seconds: number;
    skip_outcomes: string[];
    only_outcomes: string[];
    only_sentiments: string[];
    note_summary: boolean;
    note_details: boolean;
    note_link: boolean;
  };
  auto_imports: AutoRule[];
  pending_calls: number;
  config: Record<string, string>;
  pipeline: { id: string; name: string; mapped: number } | null;
  installs: { agent_id: string; agent_name: string; pipeline_id: string; pipeline_name: string; stages: string[] }[];
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
  google_sheets: "sheets.google.com", slack: "slack.com",
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

  return (
    <Card>
      <CardHeader
        title="CRM & apps"
        description="Every AI call is logged in your CRM with the summary, outcome and recording link. Import contacts to call, and have an agent call new leads within a minute."
      />
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
  const [agentId, setAgentId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const installed = new Set(c.installs.map((i) => i.agent_id));
  const free = agents.filter((a) => !installed.has(a.id));
  const tags = p.install_style === "tags";

  const install = async () => {
    if (!agentId) return;
    setBusy("install");
    setMsg(null);
    try {
      await post(`/api/integrations/crm/${p.key}/install`, { agent_id: agentId });
      const name = agents.find((a) => a.id === agentId)?.name ?? "your agent";
      setMsg({
        tone: "green",
        text: tags
          ? `Done — in ${p.name}, add the tag “AI Call - ${name}” to anyone (or bulk-tag a smart list) and ${name} calls them.`
          : `Done — open ${p.name}, find the “BlackSync AI · ${name}” pipeline and drag anyone into “Queued for AI call”.`,
      });
      setAgentId("");
      onChange();
    } catch (e) {
      setMsg({ tone: "red", text: errText(e) });
    } finally {
      setBusy(null);
    }
  };
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
            Pick an agent and you get a tag like <span className="text-zinc-200">AI Call - Marissa</span>. Tag anyone in {p.name} — one person or a
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
              <div className="text-xs text-zinc-400">Calls with {i.agent_name}</div>
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
        <div className="flex flex-col gap-2 sm:flex-row">
          <Select value={agentId} onChange={(e) => setAgentId(e.target.value)} className="sm:flex-1" aria-label="Agent for the pipeline">
            <option value="">{c.installs.length ? "Add a pipeline for another agent…" : "Pick the agent that should call…"}</option>
            {free.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
          <Button variant="primary" loading={busy === "install"} disabled={!agentId} onClick={() => void install()}>
            {tags ? "Create the tag" : `Create pipeline in ${p.name}`}
          </Button>
        </div>
      )}
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
    </div>
  );
}
