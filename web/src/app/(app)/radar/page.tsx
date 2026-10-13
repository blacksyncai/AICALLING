"use client";

import { ArrowRight, ChevronsDown, Flame, Ghost, Gift, History, Hourglass, Radar as RadarIcon, RefreshCw, Search, Snowflake, Sparkles, UserPlus, Zap } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import type { Entitlements } from "@/components/billing/types";
import { RadarPreview } from "@/components/radar/RadarPreview";
import { Badge, Button, Card, EmptyState, Input, Notice, PageHeader, Select, Spinner } from "@/components/ui";
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
  created?: string | null;
  calls?: number | null;
  contacted?: boolean | null;
}
interface Play {
  key: string;
  title: string;
  why: string;
  suggest: string;
  count: number;
  items: Item[];
}
type Depth = "quick" | "recent" | "old";
interface Scan {
  id: string;
  quick?: boolean;
  depth?: Depth;
  next?: unknown;
  batches?: number;
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

const DEPTH_LABEL: Record<Depth, string> = { quick: "quick scan", recent: "full scan", old: "old-lead dig" };

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

  const runScan = async (depth: Depth, more = false) => {
    if (!crm) return;
    setScanning(true);
    setScanErr("");
    try {
      const q = more && scan ? `continue_from=${scan.id}` : `depth=${depth}`;
      setFresh(await post<Scan>(`/api/radar/${crm.provider}/scan?${q}`));
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
      description="Scans your CRM for the people worth calling right now — pick exactly who, and hand them to an agent."
      action={
        crm ? (
          <div className="flex flex-wrap gap-2">
            <Button disabled={scanning} onClick={() => void runScan("quick")} title="Your newest 300 leads — who came in lately and hasn't been touched">
              <Zap className="h-4 w-4" /> Quick scan
            </Button>
            <Button disabled={scanning} onClick={() => void runScan("old")} title="Oldest leads first — dig up people from months or years ago">
              <History className="h-4 w-4" /> Dig old leads
            </Button>
            <Button variant="primary" loading={scanning} onClick={() => void runScan("recent")} title="Everyone with recent activity, with call history">
              <RefreshCw className="h-4 w-4" /> Full scan
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
              <span className="font-semibold text-zinc-900">{total.toLocaleString()}</span> of {scan.scanned.toLocaleString()} contacts in {crm?.name} are worth a call ·{" "}
              {DEPTH_LABEL[scan.depth ?? (scan.quick ? "quick" : "recent")]} {timeAgo(scan.created_at)}
            </p>
          ) : (
            <p className="text-sm text-zinc-600">
              Quick scan checks your newest 300 leads (seconds). Dig old leads starts from your oldest contacts. Full scan reads recent activity with call history.
            </p>
          )}
          {scan?.next ? (
            <Button size="sm" disabled={scanning} onClick={() => void runScan(scan.depth ?? "recent", true)}>
              <ChevronsDown className="h-3.5 w-3.5" /> Scan the next batch
            </Button>
          ) : null}
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

const DAY = 86_400_000;
const AGE: Record<string, [number, number] | null> = {
  any: null, d30: [0, 30], m1_6: [30, 182], m6: [182, Infinity], y1: [365, Infinity],
};
const QUIET: Record<string, number> = { any: 0, d30: 30, d90: 90, m6: 182 };

function PlayCard({ play, scanId, crm, agents }: { play: Play; scanId: string; crm: Crm; agents: { id: string; name: string }[] }) {
  const Icon = ICON[play.key] ?? RadarIcon;
  const [open, setOpen] = useState(false);
  const [picked, setAgentId] = useState<string | null>(null);
  // Default to an agent that already has a BlackSync pipeline (and still exists).
  const agentId = picked ?? (crm.installs.find((i) => agents.some((a) => a.id === i.agent_id))?.agent_id || "");
  const [busy, setBusy] = useState<"pipeline" | "campaign" | null>(null);
  const [result, setResult] = useState<{ tone: "green" | "red"; text: React.ReactNode } | null>(null);
  const [q, setQ] = useState("");
  const [added, setAdded] = useState("any");
  const [quiet, setQuiet] = useState("any");
  const [uncontacted, setUncontacted] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const installed = crm.installs.find((i) => i.agent_id === agentId);

  const filtered = useMemo(() => {
    const now = Date.now();
    const needle = q.trim().toLowerCase();
    return play.items.filter((i) => {
      if (needle && ![i.name, i.phone, i.company, i.reason, i.stage].some((v) => (v || "").toLowerCase().includes(needle))) return false;
      const age = AGE[added];
      if (age) {
        if (!i.created) return false;
        const d = (now - new Date(i.created).getTime()) / DAY;
        if (d < age[0] || d >= age[1]) return false;
      }
      if (QUIET[quiet] && (now - new Date(i.last_touch).getTime()) / DAY < QUIET[quiet]) return false;
      if (uncontacted && !(i.contacted === false || (i.contacted == null && i.calls === 0))) return false;
      return true;
    });
  }, [play.items, q, added, quiet, uncontacted]);
  const shown = open ? filtered.slice(0, 300) : filtered.slice(0, 5);
  const chosen = play.items.filter((i) => sel.has(i.external_id));
  const allShownPicked = filtered.length > 0 && filtered.every((i) => sel.has(i.external_id));
  const toggle = (id: string) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const launch = async (mode: "pipeline" | "campaign") => {
    if (!agentId || !chosen.length) return;
    setBusy(mode);
    setResult(null);
    try {
      const r = await post<{ queued?: number; failed?: number; pipeline?: string; campaign_id?: string; contacts?: number }>(
        `/api/radar/scans/${scanId}/launch`, { play: play.key, agent_id: agentId, mode, external_ids: chosen.map((i) => i.external_id) });
      setResult(mode === "pipeline"
        ? { tone: "green", text: `Queued ${r.queued} in “${r.pipeline}” — calls start within a minute (8 AM – 9 PM).` }
        : { tone: "green", text: <>Campaign ready with {r.contacts} contacts. <Link className="font-medium underline" href={`/campaigns/${r.campaign_id}`}>Review and start it →</Link></> });
      setSel(new Set());
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

      {/* Narrow it down before anyone gets called: search, age, quiet time, never contacted. */}
      <div className="space-y-2 border-b border-zinc-100 px-4 py-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, phone, stage or reason" className="pl-9" aria-label="Search" />
        </div>
        <div className="grid grid-cols-1 items-center gap-2 text-xs sm:grid-cols-2">
          <Select value={added} onChange={(e) => setAdded(e.target.value)} className="h-8 text-xs" aria-label="Added">
            <option value="any">Added: any time</option>
            <option value="d30">Added in the last 30 days</option>
            <option value="m1_6">Added 1–6 months ago</option>
            <option value="m6">Added 6+ months ago</option>
            <option value="y1">Added 1+ year ago</option>
          </Select>
          <Select value={quiet} onChange={(e) => setQuiet(e.target.value)} className="h-8 text-xs" aria-label="Last touched">
            <option value="any">Last touched: any</option>
            <option value="d30">Quiet 30+ days</option>
            <option value="d90">Quiet 90+ days</option>
            <option value="m6">Quiet 6+ months</option>
          </Select>
          <label className="flex items-center gap-1.5 text-zinc-600">
            <input type="checkbox" checked={uncontacted} onChange={(e) => setUncontacted(e.target.checked)} className="accent-brand-600" />
            Never contacted only
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-1.5 font-medium text-zinc-700">
            <input
              type="checkbox"
              checked={allShownPicked}
              onChange={() => setSel((s) => {
                const n = new Set(s);
                filtered.forEach((i) => (allShownPicked ? n.delete(i.external_id) : n.add(i.external_id)));
                return n;
              })}
              className="accent-brand-600"
            />
            Select all {filtered.length} shown
          </label>
          {sel.size > 0 && (
            <>
              <span className="text-zinc-500">{sel.size} selected</span>
              <button type="button" onClick={() => setSel(new Set())} className="text-zinc-500 hover:underline">Clear</button>
            </>
          )}
        </div>
      </div>

      <ul className={cn("divide-y divide-zinc-100 text-sm", open && "max-h-[460px] overflow-auto")}>
        {shown.map((i) => (
          <li key={i.external_id + i.phone}>
            <label className="flex cursor-pointer items-center gap-3 px-5 py-2.5 hover:bg-zinc-50">
              <input type="checkbox" checked={sel.has(i.external_id)} onChange={() => toggle(i.external_id)} className="accent-brand-600" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-zinc-900">{i.name || i.company || i.phone}</span>
                <span className="block truncate text-xs text-zinc-500">{i.reason}</span>
              </span>
              {i.stage && <Badge tone="gray" className="hidden sm:inline-flex">{i.stage}</Badge>}
            </label>
          </li>
        ))}
        {!filtered.length && <li className="px-5 py-6 text-center text-xs text-zinc-500">Nobody matches these filters.</li>}
      </ul>
      {filtered.length > 5 && (
        <button type="button" onClick={() => setOpen(!open)} className="w-full border-t border-zinc-100 py-2 text-xs font-medium text-zinc-500 hover:bg-zinc-50">
          {open ? "Show less" : `Show all ${filtered.length}`}
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
            <Button variant="primary" loading={busy === "pipeline"} disabled={!agentId || !chosen.length} onClick={() => void launch("pipeline")}>
              Queue {chosen.length || ""} in {crm.name} <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            agentId && (
              <Link href="/integrations" className="text-xs text-zinc-500 hover:text-zinc-800">
                Tip: create a BlackSync pipeline for this agent to queue them right inside {crm.name}.
              </Link>
            )
          )}
          <Button variant={installed ? "secondary" : "primary"} loading={busy === "campaign"} disabled={!agentId || !chosen.length} onClick={() => void launch("campaign")}>
            {chosen.length ? `Make a campaign of ${chosen.length}` : "Make a campaign"}
          </Button>
        </div>
        {!chosen.length && <p className="text-xs text-zinc-500">Tick the people to call — or “Select all shown” after filtering.</p>}
        {agentId && (
          <Link href={`/integrations/${crm.provider}#variables`} className="inline-flex text-xs text-zinc-500 hover:text-brand-700">
            Their {crm.name} fields fill this agent&apos;s script variables automatically · Check the mapping →
          </Link>
        )}
        {result && <Notice tone={result.tone}>{result.text}</Notice>}
      </div>
    </Card>
  );
}
