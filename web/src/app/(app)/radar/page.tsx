"use client";

import { ArrowRight, Flame, Ghost, Gift, Hourglass, Radar as RadarIcon, RefreshCw, Snowflake, Sparkles, UserPlus, Zap } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import type { Entitlements } from "@/components/billing/types";
import { RadarPreview } from "@/components/radar/RadarPreview";
import { Badge, Button, Card, EmptyState, Notice, PageHeader, Select, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import { cn, timeAgo } from "@/lib/utils";

interface Item {
  external_id: string;
  name: string;
  phone: string;
  company: string;
  reason: string;
  stage: string;
  last_touch: string;
}
interface Play {
  key: string;
  title: string;
  why: string;
  suggest: string;
  count: number;
  items: Item[];
}
interface Scan {
  id: string;
  quick?: boolean;
  provider: string;
  created_at: string;
  scanned: number;
  plays: Play[];
}
interface Crm {
  provider: string;
  name: string;
  account_label: string;
  installs: { agent_id: string; agent_name: string; pipeline_name: string }[];
  last_scan: Scan | null;
}

const ICON: Record<string, typeof Flame> = {
  hot: Flame, never_called: UserPlus, unreached: Ghost, went_cold: Snowflake, stuck: Hourglass, past_client: Gift, revive: Sparkles,
};
const TONE: Record<string, string> = {
  hot: "from-red-500/15 text-red-600", never_called: "from-brand-500/15 text-brand-600", unreached: "from-violet-500/15 text-violet-600",
  went_cold: "from-sky-500/15 text-sky-600", stuck: "from-amber-500/15 text-amber-600", past_client: "from-emerald-500/15 text-emerald-600",
  revive: "from-zinc-500/15 text-zinc-600",
};

export default function RadarPage() {
  const { session } = useSession();
  const allowed = canManage(session);
  // The server decides who has Radar (plan or admin-assigned access); everyone else gets the demo.
  const { data: ent } = useSWR<Entitlements>(allowed ? "/api/billing/entitlements" : null, fetcher);
  const entitled = !!ent?.limits.radar;
  const { data, error, mutate } = useSWR<{ crms: Crm[] }>(allowed && entitled ? "/api/radar" : null, fetcher);
  const { data: agents } = useSWR<{ id: string; name: string }[]>("/api/agents/", fetcher);
  const [crmKey, setCrmKey] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanErr, setScanErr] = useState("");
  const [fresh, setFresh] = useState<Scan | null>(null);

  const crm = data?.crms.find((c) => c.provider === crmKey) ?? data?.crms[0];
  const scan = fresh && crm && fresh.provider === crm.provider ? fresh : crm?.last_scan ?? null;

  const runScan = async (quick = false) => {
    if (!crm) return;
    setScanning(true);
    setScanErr("");
    try {
      setFresh(await post<Scan>(`/api/radar/${crm.provider}/scan${quick ? "?quick=true" : ""}`));
      void mutate();
    } catch (e) {
      setScanErr(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  const header = (
    <PageHeader
      title="Radar"
      description="Scans your CRM for the people worth calling right now — and hands them to an agent in one tap."
      action={
        crm ? (
          <div className="flex flex-wrap gap-2">
            <Button disabled={scanning} onClick={() => void runScan(true)} title="Newest 300 leads — who came in lately and hasn't been touched">
              <Zap className="h-4 w-4" /> Quick scan
            </Button>
            <Button variant="primary" loading={scanning} onClick={() => void runScan()}>
              <RefreshCw className="h-4 w-4" /> {scan ? "Full scan" : `Scan ${crm.name}`}
            </Button>
          </div>
        ) : undefined
      }
    />
  );

  if (!allowed) {
    return (
      <>
        {header}
        <Notice tone="amber">Only account owners and admins can run Radar.</Notice>
      </>
    );
  }
  if (!ent) return (<div className="flex justify-center py-20"><Spinner /></div>);
  if (!entitled) return <RadarPreview />;
  if (error) return (<>{header}<Notice tone="red">{(error as Error).message}</Notice></>);
  if (!data) return (<>{header}<div className="flex justify-center py-20"><Spinner /></div></>);
  if (!data.crms.length) {
    return (
      <>
        {header}
        <Card>
          <EmptyState
            icon={<RadarIcon className="h-5 w-5" />}
            title="Connect your CRM to use Radar"
            description="Radar reads Close or Follow Up Boss — leads, deals, calls, emails, texts, website visits — and finds who to call now."
            action={<Link href="/integrations"><Button variant="primary">Connect a CRM</Button></Link>}
          />
        </Card>
      </>
    );
  }

  const total = scan?.plays.reduce((n, p) => n + p.count, 0) ?? 0;
  return (
    <>
      {header}
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-3">
          {data.crms.length > 1 && (
            <Select value={crm?.provider} onChange={(e) => setCrmKey(e.target.value)} className="w-auto">
              {data.crms.map((c) => (
                <option key={c.provider} value={c.provider}>{c.name}</option>
              ))}
            </Select>
          )}
          {scan ? (
            <p className="text-sm text-zinc-600">
              <span className="font-semibold text-zinc-900">{total.toLocaleString()}</span> of {scan.scanned.toLocaleString()} contacts in {crm?.name} are worth a call ·
              {scan.quick ? "quick scan" : "scanned"} {timeAgo(scan.created_at)}
            </p>
          ) : (
            <p className="text-sm text-zinc-600">
              Quick scan checks your newest 300 leads for anyone not contacted yet or showing interest (seconds). Full scan reads the last 6 months of activity.
            </p>
          )}
        </div>
        {scanErr && <Notice tone="red">{scanErr}</Notice>}
        {scanning && !scan && (
          <Card className="flex items-center gap-3 p-6 text-sm text-zinc-600">
            <Spinner /> Reading leads, deals, calls, emails and texts…
          </Card>
        )}
        {scan && crm && (
          <div className="grid items-start gap-4 lg:grid-cols-2">
            {scan.plays.filter((p) => p.count > 0).map((p) => (
              <PlayCard key={p.key} play={p} scanId={scan.id} crm={crm} agents={agents ?? []} />
            ))}
            {total === 0 && <Notice tone="green">Nothing urgent — everyone has been worked recently.</Notice>}
          </div>
        )}
      </div>
    </>
  );
}

function PlayCard({ play, scanId, crm, agents }: { play: Play; scanId: string; crm: Crm; agents: { id: string; name: string }[] }) {
  const Icon = ICON[play.key] ?? RadarIcon;
  const [open, setOpen] = useState(false);
  const [picked, setAgentId] = useState<string | null>(null);
  // Default to an agent that already has a BlackSync pipeline (and still exists).
  const agentId = picked ?? (crm.installs.find((i) => agents.some((a) => a.id === i.agent_id))?.agent_id || "");
  const [busy, setBusy] = useState<"pipeline" | "campaign" | null>(null);
  const [result, setResult] = useState<{ tone: "green" | "red"; text: React.ReactNode } | null>(null);
  const installed = crm.installs.find((i) => i.agent_id === agentId);
  const shown = open ? play.items.slice(0, 100) : play.items.slice(0, 4);

  const launch = async (mode: "pipeline" | "campaign") => {
    if (!agentId) return;
    setBusy(mode);
    setResult(null);
    try {
      const r = await post<{ queued?: number; failed?: number; pipeline?: string; campaign_id?: string; contacts?: number }>(
        `/api/radar/scans/${scanId}/launch`, { play: play.key, agent_id: agentId, mode });
      setResult(mode === "pipeline"
        ? { tone: "green", text: `Queued ${r.queued} in “${r.pipeline}” — calls start within a minute (8 AM – 9 PM).` }
        : { tone: "green", text: <>Campaign ready with {r.contacts} contacts. <Link className="font-medium underline" href={`/campaigns/${r.campaign_id}`}>Review and start it →</Link></> });
    } catch (e) {
      setResult({ tone: "red", text: e instanceof Error ? e.message : "Couldn't launch" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="overflow-hidden">
      <div className={cn("bg-gradient-to-br to-transparent p-5", TONE[play.key])}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-black/5">
              <Icon className="h-5 w-5" />
            </span>
            <div>
              <div className="font-display text-lg font-semibold text-zinc-900">{play.title}</div>
              <div className="text-xs text-zinc-600">{play.why}</div>
            </div>
          </div>
          <span className="font-display text-3xl font-semibold tabular-nums text-zinc-900">{play.count}</span>
        </div>
        <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-zinc-700">
          <Zap className="h-3.5 w-3.5" /> {play.suggest}
        </p>
      </div>
      <ul className="divide-y divide-zinc-100 text-sm">
        {shown.map((i) => (
          <li key={i.external_id + i.phone} className="flex items-center gap-3 px-5 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-zinc-900">{i.name || i.company || i.phone}</span>
              <span className="block truncate text-xs text-zinc-500">{i.reason}</span>
            </span>
            {i.stage && <Badge tone="gray" className="hidden sm:inline-flex">{i.stage}</Badge>}
          </li>
        ))}
      </ul>
      {play.count > 4 && (
        <button type="button" onClick={() => setOpen(!open)} className="w-full border-t border-zinc-100 py-2 text-xs font-medium text-zinc-500 hover:bg-zinc-50">
          {open ? "Show less" : `Show ${Math.min(play.count, 100) - 4} more`}
        </button>
      )}
      <div className="space-y-3 border-t border-zinc-100 bg-zinc-50/60 p-4">
        <Select value={agentId} onChange={(e) => setAgentId(e.target.value)} aria-label="Agent">
          <option value="">Pick the agent to call them…</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}{crm.installs.some((x) => x.agent_id === a.id) ? " · has a pipeline" : ""}</option>
          ))}
        </Select>
        <div className="flex flex-wrap gap-2">
          {installed ? (
            <Button variant="primary" loading={busy === "pipeline"} disabled={!agentId} onClick={() => void launch("pipeline")}>
              Queue all {play.count} in {crm.name} <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            agentId && (
              <Link href="/integrations" className="text-xs text-zinc-500 hover:text-zinc-800">
                Tip: create a BlackSync pipeline for this agent to queue them right inside {crm.name}.
              </Link>
            )
          )}
          <Button variant={installed ? "secondary" : "primary"} loading={busy === "campaign"} disabled={!agentId} onClick={() => void launch("campaign")}>
            Make a campaign
          </Button>
        </div>
        {result && <Notice tone={result.tone}>{result.text}</Notice>}
      </div>
    </Card>
  );
}
