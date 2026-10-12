"use client";

import {
  ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpFromLine, Ban, CheckCircle2, ChevronRight, Clock, Download, FileText, Filter,
  GitBranch, History, Megaphone, Pause, PhoneCall, Play, RefreshCw, Repeat, Trash2, Zap,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { MultiPicker, type FilterDef, type Preview } from "@/components/contacts/CrmImportModal";
import {
  BlackSyncPipelines, ConnectModal, Logo, PipelineSync, errText, type Activity, type AutoRule, type Connection, type Provider,
} from "@/components/integrations/CrmIntegrations";
import { AnimatedTabList } from "@/components/ui/animated-tabs";
import { Badge, Button, Card, Field, Input, Notice, Select, Spinner, Toggle } from "@/components/ui";
import { del, fetcher, patch, post, put } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import { cn, timeAgo } from "@/lib/utils";

type Section = "push" | "pipeline" | "import" | "auto" | "triggers" | "activity";
interface Overview {
  providers: Provider[];
  connections: Connection[];
}

const OUTCOMES: { key: string; label: string }[] = [
  { key: "meeting_booked", label: "Meeting booked" }, { key: "interested", label: "Interested" },
  { key: "qualified", label: "Qualified" }, { key: "callback", label: "Callback" }, { key: "completed", label: "Talked" },
  { key: "transferred", label: "Transferred" }, { key: "not_interested", label: "Not interested" },
  { key: "not_qualified", label: "Not qualified" }, { key: "wrong_number", label: "Wrong number" },
  { key: "voicemail", label: "Voicemail" }, { key: "no_answer", label: "No answer" }, { key: "failed", label: "Failed" },
];
const SENTIMENTS = [{ key: "positive", label: "Positive" }, { key: "neutral", label: "Neutral" }, { key: "negative", label: "Negative" }];
const POSITIVE = ["meeting_booked", "interested", "qualified", "callback", "transferred"];
const PRESETS: { label: string; body: { min_seconds: number; only_outcomes: string[]; only_sentiments: string[]; only_connected: boolean } }[] = [
  { label: "Every call", body: { min_seconds: 0, only_outcomes: [], only_sentiments: [], only_connected: false } },
  { label: "Real conversations (30s+)", body: { min_seconds: 30, only_outcomes: [], only_sentiments: [], only_connected: true } },
  { label: "Positive only", body: { min_seconds: 0, only_outcomes: POSITIVE, only_sentiments: [], only_connected: true } },
  { label: "Booked meetings only", body: { min_seconds: 0, only_outcomes: ["meeting_booked"], only_sentiments: [], only_connected: true } },
];

function ruleSentence(crm: string, s: Connection["settings"]): string {
  if (!s.log_calls) return `Nothing is sent to ${crm}.`;
  const parts: string[] = [];
  if (s.only_connected) parts.push("answered");
  if (s.min_seconds) parts.push(`at least ${s.min_seconds}s long`);
  if (s.only_outcomes.length) parts.push(`ending in ${s.only_outcomes.map((k) => OUTCOMES.find((o) => o.key === k)?.label.toLowerCase() ?? k).join(" or ")}`);
  if (s.only_sentiments.length) parts.push(`where the contact sounded ${s.only_sentiments.join(" or ")}`);
  return parts.length ? `Sends calls that are ${parts.join(", ")} — plus every do-not-call request.` : `Sends every finished call to ${crm}.`;
}

function RuleRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)] sm:items-start">
      <div className="pt-1 text-sm font-medium text-zinc-700">
        {label}
        {hint && <div className="text-xs font-normal text-zinc-400">{hint}</div>}
      </div>
      <div>{children}</div>
    </div>
  );
}

const EVERY = [
  { value: 15, label: "Every 15 minutes" }, { value: 60, label: "Every hour" }, { value: 240, label: "Every 4 hours" }, { value: 1440, label: "Once a day" },
];
const everyLabel = (m: number) => EVERY.find((e) => e.value === m)?.label.toLowerCase() ?? `every ${m} min`;

const chip = (on: boolean) =>
  cn(
    "rounded-full border px-2.5 py-1 text-xs transition-colors",
    on ? "border-brand-500 bg-brand-50 font-medium text-brand-700" : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300",
  );

/** n8n-style node in the flow strip. */
function FlowNode({ icon: Icon, title, detail, active, onClick }: { icon: typeof Zap; title: string; detail: string; active?: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-w-0 flex-1 items-center gap-3 rounded-xl border bg-white px-3.5 py-3 text-left shadow-xs transition-colors",
        active ? "border-brand-300 ring-2 ring-brand-500/15" : "border-zinc-200 hover:border-zinc-300",
      )}
    >
      <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", active ? "bg-brand-600 text-white" : "bg-zinc-100 text-zinc-600")}>
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-zinc-900">{title}</span>
        <span className="block truncate text-xs text-zinc-500">{detail}</span>
      </span>
    </button>
  );
}

function Step({ n, title, hint, children, done }: { n: number; title: string; hint?: string; children: React.ReactNode; done?: boolean }) {
  return (
    <div className="relative pl-10">
      <span
        className={cn(
          "absolute left-0 top-0 flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold",
          done ? "bg-brand-600 text-white" : "bg-zinc-100 text-zinc-600 ring-1 ring-zinc-200",
        )}
      >
        {done ? <CheckCircle2 className="h-4 w-4" /> : n}
      </span>
      <div className="text-sm font-semibold text-zinc-900">{title}</div>
      {hint && <p className="mt-0.5 text-xs text-zinc-500">{hint}</p>}
      <div className="mt-3">{children}</div>
    </div>
  );
}

export default function IntegrationSetupPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = use(params);
  const router = useRouter();
  const { session } = useSession();
  const { data, error, mutate } = useSWR<Overview>("/api/integrations/crm", fetcher);
  const { data: agents } = useSWR<{ id: string; name: string }[]>("/api/agents/", fetcher);
  const [section, setSection] = useState<Section>("push");
  const [reconnect, setReconnect] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);

  const p = data?.providers.find((x) => x.key === key);
  const c = data?.connections.find((x) => x.provider === key);

  useEffect(() => {
    const h = window.location.hash.replace("#", "") as Section;
    if (["push", "pipeline", "import", "auto", "triggers", "activity"].includes(h)) setSection(h);
  }, []);

  if (!canManage(session)) return <Notice tone="amber">Only account owners and admins can manage integrations.</Notice>;
  if (error) return <Notice tone="red">{(error as Error).message}</Notice>;
  if (!data) {
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );
  }
  if (!p || !c) {
    return (
      <div className="space-y-4">
        <Link href="/integrations" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800">
          <ArrowLeft className="h-4 w-4" /> Integrations
        </Link>
        <Notice tone="amber">{p ? `${p.name} isn't connected yet.` : "Unknown integration."} Connect it from the Integrations page first.</Notice>
      </div>
    );
  }

  const isCrm = p.category === "crm";
  const sections: { id: Section; label: string; icon: React.ReactNode }[] = [
    { id: "push", label: p.category === "notify" ? "Posting calls" : "Push calls", icon: <ArrowUpFromLine className="h-4 w-4" /> },
    ...(p.pipeline_noun || p.can_install ? [{ id: "pipeline" as Section, label: "Pipeline", icon: <GitBranch className="h-4 w-4" /> }] : []),
    ...(p.can_import ? [{ id: "import" as Section, label: "Import", icon: <ArrowDownToLine className="h-4 w-4" /> }] : []),
    ...(p.can_import ? [{ id: "auto" as Section, label: `Auto-sync${c.auto_imports.length ? ` · ${c.auto_imports.length}` : ""}`, icon: <Repeat className="h-4 w-4" /> }] : []),
    ...(p.can_new_leads || p.can_activity ? [{ id: "triggers" as Section, label: "Triggers", icon: <Zap className="h-4 w-4" /> }] : []),
    { id: "activity", label: "Activity", icon: <History className="h-4 w-4" /> },
  ];
  const go = (s: Section) => {
    setSection(s);
    history.replaceState(null, "", `#${s}`);
  };
  const refresh = () => void mutate();
  const run = async (name: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(name);
    setMsg(null);
    try {
      await fn();
      if (ok) setMsg({ tone: "green", text: ok });
      refresh();
    } catch (e) {
      setMsg({ tone: "red", text: errText(e) });
    } finally {
      setBusy(null);
    }
  };

  const s = c.settings;
  const pushDetail = !s.log_calls
    ? "Off"
    : [
        s.only_outcomes.length ? `${s.only_outcomes.length} result${s.only_outcomes.length > 1 ? "s" : ""}` : s.only_connected ? "Answered calls" : "Every call",
        s.min_seconds ? `${s.min_seconds}s+` : "",
        s.only_sentiments.length ? s.only_sentiments.join("/") : "",
      ].filter(Boolean).join(" · ");
  const triggers = [s.speed_to_lead_agent_id && "Speed to lead", s.activity_agent_id && "Interest calls", c.installs.length && `${c.installs.length} AI pipeline${c.installs.length > 1 ? "s" : ""}`].filter(Boolean);

  return (
    <div className="mx-auto max-w-5xl">
      <Link href="/integrations" className="mb-4 inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-4 w-4" /> Integrations
      </Link>

      <div className="mb-6 flex flex-wrap items-center gap-4">
        <Logo p={p} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-zinc-900">{p.name}</h1>
            {c.status === "connected" ? <Badge tone="green">Connected</Badge> : <Badge tone="red">Needs attention</Badge>}
          </div>
          <p className="truncate text-sm text-zinc-500">
            {c.account_label}
            {c.last_synced_at ? ` · last sync ${timeAgo(c.last_synced_at)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" loading={busy === "test"} onClick={() => void run("test", () => post(`/api/integrations/crm/${key}/test`), "Connection checked — see Activity.")}>
            <RefreshCw className="h-3.5 w-3.5" /> Test
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setReconnect(true)}>
            Update credentials
          </Button>
          <Button
            size="sm"
            variant="danger"
            loading={busy === "delete"}
            onClick={() => {
              if (window.confirm(`Disconnect ${p.name}? Calls stop syncing and auto-sync rules are removed.`))
                void run("delete", async () => {
                  await del(`/api/integrations/crm/${key}`);
                  router.push("/integrations");
                });
            }}
          >
            <Trash2 className="h-3.5 w-3.5" /> Disconnect
          </Button>
        </div>
      </div>
      {c.status === "error" && c.last_error && (
        <div className="mb-4">
          <Notice tone="red">{c.last_error}</Notice>
        </div>
      )}
      {msg && (
        <div className="mb-4">
          <Notice tone={msg.tone}>{msg.text}</Notice>
        </div>
      )}

      {/* Flow: how data moves between BlackSync and the CRM */}
      <div className="mb-6 flex flex-col items-stretch gap-2 md:flex-row md:items-center">
        <FlowNode icon={PhoneCall} title={`Calls → ${p.name}`} detail={pushDetail} active={section === "push"} onClick={() => go("push")} />
        {(p.pipeline_noun || p.can_install) && (
          <>
            <ChevronRight className="hidden h-4 w-4 shrink-0 text-zinc-300 md:block" />
            <FlowNode
              icon={GitBranch}
              title="Stages"
              detail={c.pipeline ? `${c.pipeline.name} · ${c.pipeline.mapped} mapped` : c.installs.length ? "AI pipeline" : "Not set up"}
              active={section === "pipeline"}
              onClick={() => go("pipeline")}
            />
          </>
        )}
        {p.can_import && (
          <>
            <ChevronRight className="hidden h-4 w-4 shrink-0 text-zinc-300 md:block" />
            <FlowNode
              icon={ArrowDownToLine}
              title={`${p.name} → contacts`}
              detail={c.auto_imports.length ? `${c.auto_imports.filter((r) => r.enabled).length} auto-sync on` : "Import on demand"}
              active={section === "import" || section === "auto"}
              onClick={() => go(c.auto_imports.length ? "auto" : "import")}
            />
          </>
        )}
        {(p.can_new_leads || p.can_activity) && (
          <>
            <ChevronRight className="hidden h-4 w-4 shrink-0 text-zinc-300 md:block" />
            <FlowNode icon={Zap} title="Triggers" detail={triggers.length ? triggers.join(" · ") : "Off"} active={section === "triggers"} onClick={() => go("triggers")} />
          </>
        )}
      </div>

      <AnimatedTabList
        tabs={sections.map((x) => ({ id: x.id, label: x.label, icon: x.icon }))}
        value={section}
        onChange={go}
        variant="light"
        layoutId="integration-tab"
        className="scroll-thin mb-5 w-fit max-w-full overflow-x-auto"
      />

      {section === "push" && <PushCalls p={p} c={c} isCrm={isCrm} onSaved={refresh} />}
      {section === "pipeline" && (
        <div className="space-y-5">
          {p.pipeline_noun && <PipelineSync p={p} c={c} onSaved={refresh} />}
          {p.can_install && <BlackSyncPipelines p={p} c={c} agents={agents ?? []} onChange={refresh} />}
        </div>
      )}
      {section === "import" && <ImportBuilder p={p} onSavedRule={() => { refresh(); go("auto"); }} />}
      {section === "auto" && <AutoSync p={p} c={c} onChange={refresh} onNew={() => go("import")} />}
      {section === "triggers" && <Triggers p={p} c={c} agents={agents ?? []} onChange={refresh} />}
      {section === "activity" && <ActivityLog p={p} />}

      {reconnect && <ConnectModal p={p} existing={c} onClose={() => setReconnect(false)} onDone={() => { setReconnect(false); refresh(); }} />}
    </div>
  );
}

// ── Push calls ────────────────────────────────────────────────────────────────

function PushCalls({ p, c, isCrm, onSaved }: { p: Provider; c: Connection; isCrm: boolean; onSaved: () => void }) {
  const s = c.settings;
  const [err, setErr] = useState("");
  const save = async (body: Record<string, unknown>) => {
    setErr("");
    try {
      await patch(`/api/integrations/crm/${p.key}`, body);
      onSaved();
    } catch (e) {
      setErr(errText(e));
    }
  };
  const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
  const presetActive = (b: (typeof PRESETS)[number]["body"]) =>
    s.log_calls && s.min_seconds === b.min_seconds && s.only_connected === b.only_connected && same(s.only_outcomes, b.only_outcomes) && same(s.only_sentiments, b.only_sentiments);

  const preview = [
    "BlackSync AI call: Meeting booked",
    "Agent: Lilly · Duration 2:14",
    "Meeting: Tue 3:00 PM",
    ...(s.note_summary ? ["", "Owner is open to listing in spring; wants a price opinion first. Prefers texts after 5 PM."] : []),
    ...(s.note_details ? ["", "Timeline: 3–6 months", "Motivation: downsizing"] : []),
    ...(s.note_link ? ["", "Call details and recording: blacksync.si/calls/…"] : []),
  ].join("\n");

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-5">
        <Card className="space-y-5 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
                <Filter className="h-4 w-4 text-brand-600" /> Send a call to {p.name} when…
              </div>
              <p className="mt-0.5 text-xs text-zinc-500">Every rule must match. Do-not-call requests are always sent so {p.name} stops calling them too.</p>
            </div>
            <Toggle checked={s.log_calls} onChange={(v) => void save({ log_calls: v })} label={s.log_calls ? "On" : "Off"} />
          </div>

          <div className="flex flex-wrap gap-2">
            {PRESETS.map((pr) => (
              <button key={pr.label} type="button" onClick={() => void save({ ...pr.body, skip_outcomes: [], log_calls: true })} className={chip(presetActive(pr.body))}>
                {pr.label}
              </button>
            ))}
          </div>

          <div className={cn("space-y-4", !s.log_calls && "pointer-events-none opacity-50")}>
            <RuleRow label="It lasted at least">
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={0}
                  max={3600}
                  key={s.min_seconds}
                  defaultValue={s.min_seconds ?? 0}
                  onBlur={(e) => {
                    const v = Math.max(0, Math.min(3600, Math.round(Number(e.target.value) || 0)));
                    if (v !== s.min_seconds) void save({ min_seconds: v });
                  }}
                  className="w-24"
                  aria-label="Minimum seconds"
                />
                <span className="text-sm text-zinc-500">seconds</span>
                <span className="text-xs text-zinc-400">(0 = any length)</span>
              </div>
            </RuleRow>
            <RuleRow label="The result is" hint={s.only_outcomes.length ? undefined : "Any result"}>
              <div className="flex flex-wrap gap-1.5">
                {OUTCOMES.map((o) => {
                  const on = s.only_outcomes.includes(o.key);
                  return (
                    <button key={o.key} type="button" aria-pressed={on} onClick={() => void save({ only_outcomes: on ? s.only_outcomes.filter((x) => x !== o.key) : [...s.only_outcomes, o.key] })} className={chip(on)}>
                      {o.label}
                    </button>
                  );
                })}
              </div>
            </RuleRow>
            <RuleRow label="The contact sounded" hint={s.only_sentiments.length ? undefined : "Any mood"}>
              <div className="flex flex-wrap gap-1.5">
                {SENTIMENTS.map((o) => {
                  const on = s.only_sentiments.includes(o.key);
                  return (
                    <button key={o.key} type="button" aria-pressed={on} onClick={() => void save({ only_sentiments: on ? s.only_sentiments.filter((x) => x !== o.key) : [...s.only_sentiments, o.key] })} className={chip(on)}>
                      {o.label}
                    </button>
                  );
                })}
              </div>
            </RuleRow>
            <Toggle checked={s.only_connected} onChange={(v) => void save({ only_connected: v })} label="Only answered calls" description="Skip no-answers, voicemails and failed calls." />
            {s.skip_outcomes.length > 0 && (
              <p className="text-xs text-zinc-500">
                Also never sent: {s.skip_outcomes.map((k) => OUTCOMES.find((o) => o.key === k)?.label ?? k).join(", ")}.{" "}
                <button type="button" className="underline" onClick={() => void save({ skip_outcomes: [] })}>Clear</button>
              </p>
            )}
          </div>
          <p className="rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600 ring-1 ring-zinc-100">{ruleSentence(p.name, s)}</p>
        </Card>

        <Card className="space-y-4 p-5">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
              <FileText className="h-4 w-4 text-brand-600" /> What goes in the {isCrm ? "note" : "message"}
            </div>
            <p className="mt-0.5 text-xs text-zinc-500">The result, agent, duration and any booked meeting are always included.</p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <Toggle checked={s.note_summary} onChange={(v) => void save({ note_summary: v })} label="AI summary" />
            <Toggle checked={s.note_details} onChange={(v) => void save({ note_details: v })} label="Extracted details" />
            <Toggle checked={s.note_link} onChange={(v) => void save({ note_link: v })} label="Recording link" />
          </div>
        </Card>

        {isCrm && (
          <Card className="p-5">
            <Toggle
              checked={s.create_contacts}
              onChange={(v) => void save({ create_contacts: v })}
              label={`Create people who aren't in ${p.name}`}
              description={`Off by default. When on, a called number that isn't in ${p.name} is added quietly (no new-lead alerts). Leave off while testing with your own phone.`}
            />
          </Card>
        )}
        {err && <Notice tone="red">{err}</Notice>}
      </div>

      <div className="lg:sticky lg:top-20 lg:self-start">
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Preview in {p.name}</div>
        <pre className="whitespace-pre-wrap rounded-xl border border-zinc-200 bg-white p-4 font-sans text-xs leading-relaxed text-zinc-700 shadow-xs">{preview}</pre>
        {!s.log_calls && <p className="mt-2 text-xs text-amber-700">Logging is off — nothing is sent.</p>}
      </div>
    </div>
  );
}

// ── Import builder (step by step) ─────────────────────────────────────────────

function describe(defs: FilterDef[], filters: Record<string, string[]>): string {
  const parts: string[] = [];
  for (const f of defs) {
    if (f.type === "pipeline") {
      const pl = f.options.find((o) => o.value === filters[f.key]?.[0]);
      if (!pl) continue;
      const st = (filters[f.stage_key ?? "stages"] ?? []).map((v) => pl.stages?.find((x) => x.value === v)?.label ?? v);
      parts.push(`${pl.label}${st.length ? ` › ${st.join(", ")}` : " (all stages)"}`);
    } else {
      const v = filters[f.key] ?? [];
      if (v.length) parts.push(`${f.label}: ${v.map((x) => f.options.find((o) => o.value === x)?.label ?? x).join(", ")}`);
    }
  }
  return parts.join(" · ") || "Everyone with a phone number";
}

function ImportBuilder({ p, onSavedRule }: { p: Provider; onSavedRule: () => void }) {
  const { data: opts, error: optsError } = useSWR<{ filters: FilterDef[] }>(`/api/integrations/crm/${p.key}/import/options`, fetcher, { revalidateOnFocus: false });
  const { data: campaignList } = useSWR<{ campaigns: { id: string; name: string; status: string }[] }>("/api/campaigns/", fetcher);
  const campaigns = campaignList?.campaigns;
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [skipContacted, setSkipContacted] = useState(true);
  const [listTag, setListTag] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [every, setEvery] = useState(60);
  const [ruleName, setRuleName] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);

  const defs = opts?.filters ?? [];
  const pipeDef = defs.find((f) => f.type === "pipeline");
  const otherDefs = defs.filter((f) => f.type !== "pipeline");
  const stageKey = pipeDef?.stage_key ?? "stages";
  const pipelineId = pipeDef ? filters[pipeDef.key]?.[0] ?? "" : "";
  const pipeline = pipeDef?.options.find((o) => o.value === pipelineId);
  const stages = filters[stageKey] ?? [];
  const summary = useMemo(() => describe(defs, filters), [defs, filters]);

  useEffect(() => {
    if (!opts) return;
    let cancelled = false;
    setPreviewing(true);
    const t = window.setTimeout(async () => {
      try {
        const r = await post<Preview>(`/api/integrations/crm/${p.key}/import/preview`, { filters, skip_contacted: skipContacted });
        if (!cancelled) setPreview(r);
      } catch (e) {
        if (!cancelled) setMsg({ tone: "red", text: errText(e) });
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 600);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [opts, p.key, filters, skipContacted]);

  const importNow = async () => {
    setBusy("import");
    setMsg(null);
    try {
      const r = await post<{ created: number; linked: number; do_not_call: number; skipped_contacted: number; added_to_campaign: number }>(
        `/api/integrations/crm/${p.key}/import`,
        { filters, skip_contacted: skipContacted, list_tag: listTag, campaign_id: campaignId || null },
      );
      const camp = campaigns?.find((x) => x.id === campaignId)?.name;
      setMsg({
        tone: "green",
        text:
          `Imported ${r.created} new contact${r.created === 1 ? "" : "s"}` +
          (r.linked ? `, updated ${r.linked}` : "") +
          (r.added_to_campaign ? ` · ${r.added_to_campaign} added to “${camp}”` : "") +
          (r.do_not_call ? ` · ${r.do_not_call} on do-not-call (saved, never dialed)` : "") +
          ".",
      });
    } catch (e) {
      setMsg({ tone: "red", text: errText(e) });
    } finally {
      setBusy(null);
    }
  };
  const saveRule = async () => {
    setBusy("rule");
    setMsg(null);
    try {
      await post(`/api/integrations/crm/${p.key}/auto-imports`, {
        name: ruleName.trim() || (pipeline ? `${pipeline.label} → ${campaigns?.find((x) => x.id === campaignId)?.name ?? "contacts"}` : `${p.name} auto-sync`),
        filters, skip_contacted: skipContacted, list_tag: listTag, campaign_id: campaignId || null, every_minutes: every, summary,
      });
      onSavedRule();
    } catch (e) {
      setMsg({ tone: "red", text: errText(e) });
    } finally {
      setBusy(null);
    }
  };

  if (optsError) return <Notice tone="red">Couldn&apos;t load {p.name} filters: {(optsError as Error).message}</Notice>;
  if (!opts) {
    return (
      <Card className="flex items-center gap-2 p-5 text-sm text-zinc-500">
        <Spinner /> Reading your {p.name} pipelines, stages and lists…
      </Card>
    );
  }

  let n = 0;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="space-y-7 p-5">
        {pipeDef && (
          <Step n={++n} title="Pick the pipeline" hint={`Only people with an ${p.pipeline_noun || "item"} in this pipeline.`} done={!!pipelineId}>
            <div className="grid gap-2 sm:grid-cols-2">
              <button type="button" onClick={() => setFilters({ ...filters, [pipeDef.key]: [], [stageKey]: [] })} className={cn("rounded-xl border p-3 text-left text-sm", !pipelineId ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-zinc-200 hover:border-zinc-300")}>
                <div className="font-medium text-zinc-900">Any pipeline</div>
                <div className="text-xs text-zinc-500">Don&apos;t filter by pipeline</div>
              </button>
              {pipeDef.options.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => setFilters({ ...filters, [pipeDef.key]: [o.value], [stageKey]: [] })}
                  className={cn("rounded-xl border p-3 text-left text-sm", pipelineId === o.value ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-zinc-200 hover:border-zinc-300")}
                >
                  <div className="truncate font-medium text-zinc-900">{o.label}</div>
                  <div className="text-xs text-zinc-500">{o.stages?.length ?? 0} stages</div>
                </button>
              ))}
            </div>
          </Step>
        )}

        {pipeDef && pipeline && (
          <Step n={++n} title="Pick the stages" hint="Only people sitting in these stages. None picked = every stage." done={stages.length > 0}>
            <div className="scroll-thin flex gap-2 overflow-x-auto pb-1">
              {(pipeline.stages ?? []).map((st, i) => {
                const on = stages.includes(st.value);
                return (
                  <div key={st.value} className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => setFilters({ ...filters, [stageKey]: on ? stages.filter((x) => x !== st.value) : [...stages, st.value] })}
                      className={cn(
                        "w-36 rounded-xl border p-3 text-left transition-colors",
                        on ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-zinc-200 bg-white hover:border-zinc-300",
                      )}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-[10px] font-medium uppercase tracking-wide text-zinc-400">Stage {i + 1}</span>
                        {on && <CheckCircle2 className="h-3.5 w-3.5 text-brand-600" />}
                      </div>
                      <div className="mt-1 line-clamp-2 text-sm font-medium text-zinc-900">{st.label}</div>
                      {st.kind !== "active" && <div className="mt-0.5 text-[11px] text-zinc-500">{st.kind}</div>}
                    </button>
                    {i < (pipeline.stages?.length ?? 0) - 1 && <ArrowRight className="h-3.5 w-3.5 text-zinc-300" />}
                  </div>
                );
              })}
            </div>
          </Step>
        )}

        {otherDefs.length > 0 && (
          <Step n={++n} title="Narrow it down (optional)" hint="Every filter you add must match." done={otherDefs.some((f) => (filters[f.key] ?? []).length)}>
            <div className="grid gap-5 md:grid-cols-2">
              {otherDefs.map((f) =>
                f.type === "multi" ? (
                  <MultiPicker key={f.key} f={f} value={filters[f.key] ?? []} onChange={(v) => setFilters({ ...filters, [f.key]: v })} />
                ) : (
                  <Field key={f.key} label={f.label}>
                    <Select value={filters[f.key]?.[0] ?? ""} onChange={(e) => setFilters({ ...filters, [f.key]: e.target.value ? [e.target.value] : [] })}>
                      <option value="">Any</option>
                      {f.options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                ),
              )}
            </div>
          </Step>
        )}

        <Step n={++n} title="Where they go" hint="Do-not-call people are always saved but never dialed." done={!!campaignId}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Add to a campaign" hint="New contacts join its call list right away.">
              <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
                <option value="">Just add to Contacts</option>
                {(campaigns ?? []).filter((x) => x.status !== "cancelled").map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name} · {x.status}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Tag them (optional)">
              <Input value={listTag} maxLength={60} placeholder={`e.g. ${p.name} hot leads`} onChange={(e) => setListTag(e.target.value)} />
            </Field>
            <div className="md:col-span-2">
              <Toggle checked={skipContacted} onChange={setSkipContacted} label="Skip people already contacted" description={`Leave out anyone ${p.name} shows you've already called, texted or emailed.`} />
            </div>
          </div>
        </Step>
      </Card>

      <div className="space-y-3 lg:sticky lg:top-20 lg:self-start">
        <Card className="p-4">
          <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">Matching now</div>
          {previewing && !preview ? (
            <div className="mt-2 flex items-center gap-2 text-sm text-zinc-500">
              <Spinner /> Counting…
            </div>
          ) : preview ? (
            <>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="font-display text-3xl font-semibold tabular-nums text-zinc-900">{preview.will_import.toLocaleString()}</span>
                <span className="text-sm text-zinc-500">new to import</span>
                {previewing && <Spinner className="h-3.5 w-3.5" />}
              </div>
              <ul className="mt-2 space-y-1 text-xs text-zinc-600">
                <li>{preview.found.toLocaleString()} matched in {p.name}</li>
                {preview.already_in_blacksync > 0 && <li>{preview.already_in_blacksync} already in BlackSync</li>}
                {preview.do_not_call > 0 && <li className="text-red-600">{preview.do_not_call} do-not-call (saved, never dialed)</li>}
                {preview.skipped_contacted > 0 && <li className="text-amber-700">{preview.skipped_contacted} skipped — already contacted</li>}
              </ul>
              {preview.sample.length > 0 && (
                <ul className="mt-3 divide-y divide-zinc-100 rounded-lg text-xs ring-1 ring-zinc-100">
                  {preview.sample.slice(0, 5).map((x) => (
                    <li key={x.phone + x.name} className="flex items-center gap-2 px-2.5 py-1.5">
                      <span className="min-w-0 flex-1 truncate font-medium text-zinc-800">{x.name || "Unnamed"}</span>
                      {x.stage && <span className="truncate text-zinc-400">{x.stage}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : null}
          <p className="mt-3 border-t border-zinc-100 pt-3 text-xs text-zinc-500">{summary}</p>
          <Button variant="primary" className="mt-3 w-full justify-center" loading={busy === "import"} disabled={!preview || preview.found === 0} onClick={() => void importNow()}>
            <Download className="h-4 w-4" /> Import {preview ? preview.will_import.toLocaleString() : ""} now
          </Button>
        </Card>

        <Card className="space-y-3 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
            <Repeat className="h-4 w-4 text-brand-600" /> Keep it in sync
          </div>
          <p className="text-xs text-zinc-500">
            Save this as a rule: BlackSync checks {p.name} on a schedule and brings in anyone new who matches{campaignId ? " — straight into the campaign’s call list" : ""}.
          </p>
          <Input value={ruleName} maxLength={80} placeholder="Rule name (optional)" onChange={(e) => setRuleName(e.target.value)} />
          <Select value={String(every)} onChange={(e) => setEvery(Number(e.target.value))}>
            {EVERY.map((e) => (
              <option key={e.value} value={e.value}>
                {e.label}
              </option>
            ))}
          </Select>
          <Button className="w-full justify-center" loading={busy === "rule"} onClick={() => void saveRule()}>
            <Repeat className="h-4 w-4" /> Save as auto-sync
          </Button>
        </Card>
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      </div>
    </div>
  );
}

// ── Auto-sync rules ───────────────────────────────────────────────────────────

function AutoSync({ p, c, onChange, onNew }: { p: Provider; c: Connection; onChange: () => void; onNew: () => void }) {
  const { data: campaignList } = useSWR<{ campaigns: { id: string; name: string }[] }>("/api/campaigns/", fetcher);
  const campaigns = campaignList?.campaigns;
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const campName = (id: string | null) => (id ? campaigns?.find((x) => x.id === id)?.name ?? "a campaign" : null);

  const act = async (id: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(id);
    setMsg(null);
    try {
      await fn();
      if (ok) setMsg({ tone: "green", text: ok });
      onChange();
    } catch (e) {
      setMsg({ tone: "red", text: errText(e) });
    } finally {
      setBusy(null);
    }
  };
  const toggle = (r: AutoRule) =>
    act(r.id, () => put(`/api/integrations/crm/${p.key}/auto-imports/${r.id}`, { ...r, enabled: !r.enabled }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-zinc-600">
          Rules re-run a saved import on a schedule. New people who match are added to Contacts (and the chosen campaign, which starts calling them if it had
          finished its list). People already in BlackSync are never duplicated.
        </p>
        <Button variant="primary" size="sm" onClick={onNew}>
          <Repeat className="h-3.5 w-3.5" /> New rule
        </Button>
      </div>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      {c.auto_imports.length === 0 ? (
        <Card className="p-8 text-center">
          <Repeat className="mx-auto h-6 w-6 text-zinc-300" />
          <div className="mt-2 text-sm font-medium text-zinc-900">No auto-sync rules yet</div>
          <p className="mx-auto mt-1 max-w-md text-xs text-zinc-500">
            Example: every 15 minutes, anyone new in “{p.pipeline_noun ? "Sales pipeline › Qualified" : "Hot prospects"}” goes straight into your calling campaign.
          </p>
          <Button className="mt-4" size="sm" onClick={onNew}>
            Build one from an import
          </Button>
        </Card>
      ) : (
        <div className="space-y-3">
          {c.auto_imports.map((r) => (
            <Card key={r.id} className={cn("p-4", !r.enabled && "opacity-70")}>
              <div className="flex flex-wrap items-start gap-3">
                <span className={cn("mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", r.enabled ? "bg-brand-50 text-brand-600" : "bg-zinc-100 text-zinc-400")}>
                  <Repeat className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-zinc-900">{r.name}</span>
                    <Badge tone={r.enabled ? "green" : "gray"}>{r.enabled ? "On" : "Paused"}</Badge>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-zinc-600">
                    <span className="rounded-md bg-zinc-100 px-1.5 py-0.5">{r.summary || "Everyone with a phone"}</span>
                    <ArrowRight className="h-3 w-3 text-zinc-400" />
                    <span className="inline-flex items-center gap-1 rounded-md bg-zinc-100 px-1.5 py-0.5">
                      {r.campaign_id ? <Megaphone className="h-3 w-3" /> : null}
                      {campName(r.campaign_id) ?? "Contacts"}
                    </span>
                    {r.list_tag && <span className="rounded-md bg-zinc-100 px-1.5 py-0.5">tag: {r.list_tag}</span>}
                    {r.skip_contacted && <span className="text-zinc-400">· skips contacted</span>}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" /> {everyLabel(r.every_minutes)}
                    </span>
                    <span>
                      {r.last_run_at ? `Last run ${timeAgo(r.last_run_at)}` : "Hasn't run yet"}
                      {r.last_result?.ok && ` · +${r.last_result.created ?? 0} new${r.last_result.added ? `, ${r.last_result.added} queued` : ""}`}
                    </span>
                    {r.last_result && !r.last_result.ok && <span className="text-red-600">Failed: {r.last_result.error}</span>}
                    <span>{r.runs} run{r.runs === 1 ? "" : "s"}</span>
                  </div>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button size="sm" loading={busy === `run-${r.id}`} onClick={() => void act(`run-${r.id}`, () => post(`/api/integrations/crm/${p.key}/auto-imports/${r.id}/run`), `Ran “${r.name}”.`)}>
                    <Play className="h-3.5 w-3.5" /> Run now
                  </Button>
                  <Button size="sm" variant="ghost" loading={busy === r.id} onClick={() => void toggle(r)} aria-label={r.enabled ? "Pause rule" : "Resume rule"}>
                    {r.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Delete rule"
                    onClick={() => {
                      if (window.confirm(`Delete “${r.name}”? Contacts it already imported stay.`)) void act(`del-${r.id}`, () => del(`/api/integrations/crm/${p.key}/auto-imports/${r.id}`));
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Triggers (speed to lead, interest calls) ──────────────────────────────────

function Triggers({ p, c, agents, onChange }: { p: Provider; c: Connection; agents: { id: string; name: string }[]; onChange: () => void }) {
  const s = c.settings;
  const [err, setErr] = useState("");
  const save = async (body: Record<string, unknown>) => {
    setErr("");
    try {
      await patch(`/api/integrations/crm/${p.key}`, body);
      onChange();
    } catch (e) {
      setErr(errText(e));
    }
  };
  return (
    <div className="grid gap-5 md:grid-cols-2">
      {p.can_new_leads && (
        <Card className="space-y-3 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
            <Zap className="h-4 w-4 text-brand-600" /> Speed to lead
          </div>
          <p className="text-xs text-zinc-600">
            When a new lead lands in {p.name}, this agent calls them within about a minute (8 AM – 9 PM in your account&apos;s time zone; later leads are called when the
            window opens). Uses calling credits.
          </p>
          <Select value={s.speed_to_lead_agent_id ?? ""} onChange={(e) => void save({ speed_to_lead_agent_id: e.target.value })} aria-label="Speed to lead agent">
            <option value="">Off</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                Call with {a.name}
              </option>
            ))}
          </Select>
          {c.pending_calls > 0 && <p className="text-xs text-zinc-600">{c.pending_calls} new lead(s) waiting for calling hours.</p>}
        </Card>
      )}
      {p.can_activity && (
        <Card className="space-y-3 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
            <Zap className="h-4 w-4 text-red-500" /> Call when they show interest
          </div>
          <p className="text-xs text-zinc-600">
            When someone in {p.name} views or saves a listing, sends an inquiry or registers, this agent calls them within about a minute and knows what they looked
            at. Skips anyone called in the last 24 hours. 8 AM – 9 PM. Uses calling credits.
          </p>
          <Select value={s.activity_agent_id ?? ""} onChange={(e) => void save({ activity_agent_id: e.target.value })} aria-label="Agent for interest calls">
            <option value="">Off</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                Call with {a.name}
              </option>
            ))}
          </Select>
        </Card>
      )}
      {err && <Notice tone="red">{err}</Notice>}
    </div>
  );
}

// ── Activity ──────────────────────────────────────────────────────────────────

function ActivityLog({ p }: { p: Provider }) {
  const { data } = useSWR<{ items: Activity[] }>(`/api/integrations/crm/${p.key}/activity`, fetcher, { refreshInterval: 15000 });
  const [kind, setKind] = useState("all");
  if (!data) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }
  const kinds = Array.from(new Set(data.items.map((a) => a.kind)));
  const items = data.items.filter((a) => kind === "all" || (kind === "error" ? a.status === "error" : a.kind === kind));
  const LABEL: Record<string, string> = { call: "Calls", import: "Imports", test: "Setup", lead: "New leads", queue: "Pipeline" };
  return (
    <Card>
      <div className="flex flex-wrap gap-1.5 border-b border-zinc-100 p-3">
        {["all", ...kinds, "error"].map((k) => (
          <button key={k} type="button" onClick={() => setKind(k)} className={chip(kind === k)}>
            {k === "all" ? "Everything" : k === "error" ? "Errors" : LABEL[k] ?? k}
          </button>
        ))}
      </div>
      {items.length === 0 ? (
        <p className="p-5 text-sm text-zinc-500">Nothing here yet — finished calls and imports show up as they happen.</p>
      ) : (
        <ul className="divide-y divide-zinc-100 text-sm">
          {items.map((a) => (
            <li key={a.id} className="flex items-start gap-3 px-4 py-2.5">
              <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", a.status === "ok" ? "bg-emerald-500" : "bg-red-500")} />
              <span className="min-w-0 flex-1 text-zinc-700">{a.message}</span>
              <span className="shrink-0 text-xs text-zinc-400">{timeAgo(a.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
