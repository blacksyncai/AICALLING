"use client";

import { AlertTriangle, CalendarDays, Info, RotateCw } from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Button, Card, Select, Spinner } from "@/components/ui";
import type { Cell } from "@/components/ui/contribution-skyline";
import { fetcher } from "@/lib/api";
import type { ActivityDay, ActivityMetric, ActivityRange, ActivityResponse, Agent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { METRICS, RANGES, dayHref, formatDay, metricInfo, rangeInfo, timeZoneLabel } from "./activity-model";

// The skyline draws on a canvas and measures the DOM, so it only renders in the browser.
const ContributionSkyline = dynamic(() => import("@/components/ui/contribution-skyline"), {
  ssr: false,
  loading: () => <Skeleton />,
});

function Skeleton() {
  return (
    <div aria-hidden="true" className="flex flex-col gap-3">
      <div className="h-5 w-48 animate-pulse rounded bg-zinc-100" />
      <div className="h-[168px] animate-pulse rounded-lg bg-zinc-100" />
    </div>
  );
}

const nf = new Intl.NumberFormat("en-US");

function Line({ label, value, strong }: { label: string; value: number; strong?: boolean }) {
  return (
    <>
      <dt className={cn("opacity-70", strong && "opacity-100")}>{label}</dt>
      <dd className={cn("text-right tabular-nums", strong && "font-semibold")}>{nf.format(value)}</dd>
    </>
  );
}

export function ActivityHeatmap() {
  const router = useRouter();
  const [metric, setMetric] = useState<ActivityMetric>("calls");
  const [range, setRange] = useState<ActivityRange>("12m");
  const [agentId, setAgentId] = useState("");
  const [view, setView] = useState<"2d" | "3d">("2d");
  // Touch screens have no hover: the first tap shows a day, the second opens it.
  const [touch, setTouch] = useState(false);
  useEffect(() => {
    try {
      setTouch(window.matchMedia("(hover: none)").matches);
    } catch {
      /* older browsers: assume a mouse */
    }
  }, []);

  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const qs = new URLSearchParams({ metric, range });
  if (agentId) qs.set("agent_id", agentId);
  const { data, error, isValidating, mutate } = useSWR<ActivityResponse>(`/api/activity/daily?${qs}`, fetcher, {
    keepPreviousData: true,
  });

  // A stale agent filter (e.g. the agent was deleted) falls back to all agents.
  useEffect(() => {
    if (agentId && agents && !agents.some((a) => a.id === agentId)) setAgentId("");
  }, [agentId, agents]);

  // While new numbers load, the previous ones stay up (labelled by their own metric) with a small spinner.
  const shown = data;
  const rInfo = rangeInfo(shown?.range ?? range);
  const tzLabel = shown ? timeZoneLabel(shown.timezone) : null;

  const details = useMemo(() => {
    const m = new Map<string, ActivityDay>();
    for (const d of shown?.days ?? []) m.set(d.date, d);
    return m;
  }, [shown]);
  const chartData = useMemo(() => (shown?.days ?? []).map((d) => ({ date: d.date, count: d.value })), [shown]);

  const sInfo = metricInfo(shown?.metric ?? metric);
  const agentFilter = shown?.agent?.id ?? null;

  const renderTooltip = useCallback(
    (cell: Cell) => {
      const d = details.get(cell.date);
      const n = cell.count;
      return (
        <div className="flex flex-col gap-1.5">
          <div>
            <div className="text-[11px] opacity-70">{formatDay(cell.date, { weekday: "short", month: "short", day: "numeric", year: "numeric" })}</div>
            <div className="font-semibold">{n ? `${nf.format(n)} ${n === 1 ? sInfo.unit : sInfo.unitPlural}` : `No ${sInfo.unitPlural}`}</div>
          </div>
          {d && (
            <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 text-[11px]">
              <Line label="Phone calls" value={d.calls} strong={sInfo.value === "calls"} />
              <Line label="Connected" value={d.connected} strong={sInfo.value === "connected"} />
              <Line label="Appointments booked" value={d.appointments} strong={sInfo.value === "appointments"} />
              <Line label="Warm transfers" value={d.transfers} strong={sInfo.value === "transfers"} />
              {shown?.credits_tracked && <Line label="Credits used" value={d.credits} strong={sInfo.value === "credits"} />}
            </dl>
          )}
          {d && d.agents.length > 0 && !agentFilter && (
            <div className="border-t border-white/15 pt-1.5 text-[11px]">
              <div className="mb-0.5 opacity-70">By agent</div>
              <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5">
                {d.agents.map((a) => (
                  <Line key={a.id ?? "removed"} label={a.name} value={a.value} />
                ))}
              </dl>
            </div>
          )}
          <div className="text-[11px] opacity-70">
            {touch ? "Tap again" : "Click"} to open {sInfo.opens}
          </div>
        </div>
      );
    },
    [details, sInfo, shown?.credits_tracked, agentFilter, touch],
  );

  const onCellClick = useCallback(
    (cell: Cell) => router.push(dayHref(cell.date, sInfo.value, agentFilter)),
    [router, sInfo.value, agentFilter],
  );

  const agentName = shown?.agent?.name;
  const noActivity = shown && shown.totals.calls === 0 && shown.totals.credits === 0;

  return (
    <Card className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 px-4 pt-4 sm:px-5 sm:pt-5">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 font-semibold">
            AI Calling Activity
            {isValidating && shown && <Spinner className="h-3.5 w-3.5" />}
          </h3>
          <p className="text-sm text-zinc-500">Daily activity across your AI agents</p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <Select
            aria-label="What to show"
            className="h-8 w-auto min-w-0 max-w-full flex-1 text-xs sm:flex-none"
            value={metric}
            onChange={(e) => setMetric(e.target.value as ActivityMetric)}
          >
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Agent"
            className="h-8 w-auto min-w-0 max-w-full flex-1 text-xs sm:max-w-44 sm:flex-none"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
          >
            <option value="">All agents</option>
            {agents?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
          <div className="flex rounded-lg border border-zinc-200 bg-white p-0.5" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button
                key={r.value}
                type="button"
                onClick={() => setRange(r.value)}
                aria-pressed={range === r.value}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-brand-500",
                  range === r.value ? "bg-zinc-900 text-white" : "text-zinc-600 hover:text-zinc-900",
                )}
              >
                {r.short}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="px-4 pt-3 pb-4 sm:px-5 sm:pb-5">
        {error && !shown ? (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-zinc-200 px-4 py-10 text-center">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            <div>
              <p className="text-sm font-medium text-zinc-900">Couldn&apos;t load your calling activity</p>
              <p className="mt-0.5 text-xs text-zinc-500">{error.message}</p>
            </div>
            <Button size="sm" onClick={() => mutate()}>
              <RotateCw className="h-3.5 w-3.5" /> Try again
            </Button>
          </div>
        ) : !shown ? (
          <Skeleton />
        ) : !shown.metric_available ? (
          <div className="flex items-start gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-4 text-sm text-zinc-700">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
            <p>
              <span className="font-medium">{sInfo.label} isn&apos;t available.</span> {shown.note}
            </p>
          </div>
        ) : noActivity ? (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-zinc-200 px-4 py-10 text-center">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              <CalendarDays className="h-5 w-5" />
            </span>
            <p className="text-sm font-medium text-zinc-900">No calls in this period yet</p>
            <p className="max-w-sm text-xs text-zinc-500">
              {agentName ? `${agentName} hasn't placed any phone calls in the ${rInfo.label}.` : `Phone calls your agents place in the ${rInfo.label} will show up here, one square per day.`}
            </p>
          </div>
        ) : (
          <>
            {error && (
              <p className="mb-2 flex items-center gap-1.5 text-xs text-amber-700">
                <AlertTriangle className="h-3.5 w-3.5" /> Couldn&apos;t refresh — showing the last loaded numbers.
                <button type="button" className="font-medium underline" onClick={() => mutate()}>
                  Retry
                </button>
              </p>
            )}
            <ContributionSkyline
              bare
              data={chartData}
              startDate={shown.start}
              endDate={shown.end}
              rangeLabel={rInfo.label}
              view={view}
              onViewChange={setView}
              unit={sInfo.unit}
              unitPlural={sInfo.unitPlural}
              title={
                <>
                  <span className="font-semibold tabular-nums">{nf.format(shown.totals.value)}</span>{" "}
                  {shown.totals.value === 1 ? sInfo.unit : sInfo.unitPlural} in the {rInfo.label}
                  {agentName ? <span className="text-zinc-500"> · {agentName}</span> : null}
                </>
              }
              maxHeight3d={420}
              maxCell={28}
              renderTooltip={renderTooltip}
              onCellClick={onCellClick}
            />
            <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
              Shades and heights are relative to your busiest days in this period (95th percentile). Phone calls only — browser test calls
              aren&apos;t counted.
              {sInfo.value === "transfers" && " A warm transfer counts when your agent handed the call to your team and the phone system accepted it."}
              {sInfo.value === "credits" && " Credits come from your credit history, on the day they were charged."}
              {tzLabel && <> Days in {tzLabel}.</>}
            </p>
          </>
        )}
      </div>
    </Card>
  );
}
