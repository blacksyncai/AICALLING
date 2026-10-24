"use client";

import { BarChart3 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { bestHours, describeHours, toLocalHours } from "@/components/analytics/hours";
import { BestTimeCard, CallsHero, FunnelCard, KpiTiles, MoodCard, OutcomesCard, ReachGauge } from "@/components/analytics/Bento";
import { AgentTable, CampaignTable } from "@/components/analytics/Panels";
import type { Analytics } from "@/components/analytics/types";
import { Button, Card, CardHeader, EmptyState, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { cn } from "@/lib/utils";

const RANGES = [7, 30, 90] as const;

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
  // Leaderboards only earn space once there's something to compare.
  const boards = [
    ...(data && !data.locked?.includes("by_agent") && data.by_agent.length >= 2 ? [{ title: "Agent leaderboard", body: <AgentTable rows={data.by_agent} /> }] : []),
    ...(data && data.by_campaign.length >= 2 ? [{ title: "Campaign leaderboard", body: <CampaignTable rows={data.by_campaign} /> }] : []),
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
          <p className="mt-1 text-sm text-zinc-500">How your phone calls turn into meetings, last {days} days.</p>
        </div>
        <div className="flex gap-0.5 rounded-2xl bg-zinc-900 p-1" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setDays(r)}
              className={cn("min-w-11 rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors", days === r ? "bg-white text-zinc-900" : "text-white/55 hover:text-white")}
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
          <div className="relative overflow-hidden rounded-[32px] bg-[#0a0a0b] p-3 shadow-[0_40px_80px_-40px_rgba(0,0,0,.6)] sm:p-4">
            <div className="pointer-events-none absolute -left-40 -top-40 h-[480px] w-[480px] rounded-full bg-[#e2541f] opacity-[.12] blur-[120px]" />
            <div className="relative grid grid-cols-12 gap-3 sm:gap-4">
              <CallsHero data={data} />
              <ReachGauge data={data} />
              <KpiTiles data={data} />
              <FunnelCard funnel={f} />
              <OutcomesCard outcomes={data.outcomes} />
              <BestTimeCard hours={hours} best={best} />
              <MoodCard sentiment={data.sentiment} className="col-span-12" />
            </div>
          </div>
          {boards.length > 0 && (
            <div className="grid grid-cols-12 gap-4">
              {boards.map((b) => (
                <Card key={b.title} className={cn("col-span-12 min-w-0", boards.length === 2 && "xl:col-span-6")}>
                  <CardHeader title={b.title} description="Ranked by meetings booked" />
                  <div className="pt-1">{b.body}</div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
