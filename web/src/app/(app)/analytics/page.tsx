"use client";

import { BarChart3, Clock, Coins, PhoneCall, PhoneIncoming, CalendarCheck } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { bestHours, describeHours, toLocalHours } from "@/components/analytics/hours";
import { AgentTable, CampaignTable, FunnelChart, OutcomeBars, SentimentBar } from "@/components/analytics/Panels";
import { pct, type Analytics } from "@/components/analytics/types";
import { Button, Card, CardHeader, EmptyState, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { cn, formatDuration } from "@/lib/utils";

// Recharts measures the DOM, so render the chart on the client only.
const BestTimeChart = dynamic(() => import("@/components/analytics/BestTimeChart").then((m) => m.BestTimeChart), {
  ssr: false,
  loading: () => <div className="h-56 animate-pulse rounded-lg bg-zinc-100" />,
});

const RANGES = [7, 30, 90] as const;

function StatCard({ label, value, icon: Icon, hint }: { label: string; value: string; icon: typeof PhoneCall; hint: React.ReactNode }) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <span className="text-sm font-medium text-zinc-600">{label}</span>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 font-display text-3xl font-semibold tabular-nums tracking-tight">{value}</div>
      <div className="mt-1 text-xs text-zinc-500">{hint}</div>
    </Card>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const { data, error } = useSWR<Analytics>(`/api/analytics?days=${days}`, fetcher, { refreshInterval: 60000, keepPreviousData: true });

  const hours = useMemo(() => (data ? toLocalHours(data.by_hour) : []), [data]);
  const best = useMemo(() => bestHours(hours), [hours]);

  if (error) {
    return (
      <Card>
        <EmptyState icon={<BarChart3 className="h-5 w-5" />} title="Couldn't load analytics" description={error.message} />
      </Card>
    );
  }

  const f = data?.funnel;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
          <p className="mt-1 text-sm text-zinc-500">How your phone calls turn into meetings, last {days} days.</p>
        </div>
        <div className="flex rounded-lg border border-zinc-200 bg-white p-0.5" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setDays(r)}
              className={cn("rounded-md px-3 py-1.5 text-xs font-medium transition-colors", days === r ? "bg-zinc-900 text-white" : "text-zinc-600 hover:text-zinc-900")}
              aria-pressed={days === r}
            >
              {r}d
            </button>
          ))}
        </div>
      </div>

      {!data || !f ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : f.dialed === 0 ? (
        <Card>
          <EmptyState
            icon={<BarChart3 className="h-5 w-5" />}
            title={`No phone calls in the last ${days} days`}
            description="Once your agents start calling, you'll see where calls drop off, which agents and campaigns book the most meetings, and the best hours to call."
            action={
              <Link href="/campaigns">
                <Button variant="primary">Start a campaign</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Calls placed" value={f.dialed.toLocaleString()} icon={PhoneCall} hint={`${data.total_minutes.toLocaleString()} minutes of talk time`} />
            <StatCard label="Connect rate" value={`${pct(f.connected, f.dialed)}%`} icon={PhoneIncoming} hint={`${f.connected.toLocaleString()} people picked up`} />
            <StatCard label="Booking rate" value={`${pct(f.booked, f.connected)}%`} icon={CalendarCheck} hint={`${f.booked.toLocaleString()} meeting${f.booked === 1 ? "" : "s"} from connected calls`} />
            <StatCard
              label="Avg call length"
              value={formatDuration(data.avg_talk_seconds)}
              icon={Clock}
              hint={
                <span className="inline-flex items-center gap-1">
                  <Coins className="h-3 w-3" /> {data.credits_used.toLocaleString()} credit{data.credits_used === 1 ? "" : "s"} used
                </span>
              }
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-5">
            <Card className="min-w-0 lg:col-span-3">
              <CardHeader title="From dial to meeting" description="How many calls make it through each step" />
              <div className="p-5">
                <FunnelChart funnel={f} />
              </div>
            </Card>
            <Card className="min-w-0 lg:col-span-2">
              <CardHeader title="How calls ended" description="Outcome of every call in this period" />
              <div className="p-5">
                <OutcomeBars outcomes={data.outcomes} />
              </div>
            </Card>
          </div>

          <Card className="min-w-0">
            <CardHeader title="Best time to call" description="Share of calls answered at each hour, in your local time" />
            <div className="p-5">
              {best.length > 0 ? (
                <p className="mb-4 text-sm text-zinc-700">
                  Your best connect rates are <span className="font-semibold text-brand-700">{describeHours(best)}</span>. Schedule campaigns around these hours to reach more people.
                </p>
              ) : (
                <p className="mb-4 text-sm text-zinc-500">Nobody has picked up yet — keep calling and the best hours will show here.</p>
              )}
              <BestTimeChart hours={hours} best={best} />
            </div>
          </Card>

          <div className="grid gap-6 xl:grid-cols-2">
            <Card className="min-w-0">
              <CardHeader title="Agent leaderboard" description="Ranked by meetings booked" />
              <div className="pt-1">
                {data.locked?.includes("by_agent") ? (
                  <div className="px-6 pb-6 pt-2 text-sm text-zinc-600">
                    Compare agents side by side with team analytics on the Teams plan.{" "}
                    <Link href="/billing?tab=plans&plan=teams" className="font-medium text-brand-700 hover:text-brand-800">
                      See Teams
                    </Link>
                  </div>
                ) : (
                  <AgentTable rows={data.by_agent} />
                )}
              </div>
            </Card>
            <Card className="min-w-0">
              <CardHeader title="Campaign leaderboard" description="Ranked by meetings booked" />
              <div className="pt-1">
                <CampaignTable rows={data.by_campaign} />
              </div>
            </Card>
          </div>

          <Card className="min-w-0">
            <CardHeader title="Prospect mood" description="How people felt on the call, from the AI's read of each conversation" />
            <div className="p-5">
              <SentimentBar sentiment={data.sentiment} />
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
