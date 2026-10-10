"use client";

import { Bot, CalendarCheck, CalendarDays, CalendarRange, UserCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { MeetingCard } from "@/components/meetings/MeetingCard";
import { MEETING_STATUS, type MeetingStatus, type MeetingsResponse } from "@/components/meetings/types";
import { useToast } from "@/components/toast";
import { Button, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { fetcher, patch } from "@/lib/api";
import { cn } from "@/lib/utils";

type Filter = "all" | MeetingStatus;

function StatCard({ label, value, icon: Icon, hint }: { label: string; value: string; icon: typeof CalendarCheck; hint: string }) {
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

export default function MeetingsPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [saving, setSaving] = useState<string | null>(null);
  const toast = useToast();
  const key = "/api/meetings?status=all";
  const { data, error, mutate } = useSWR<MeetingsResponse>(key, fetcher, { refreshInterval: 30000 });

  async function setStatus(callId: string, status: MeetingStatus) {
    if (!data) return;
    setSaving(callId);
    // Update the card right away; re-sync counts from the server after.
    const optimistic = { ...data, items: data.items.map((m) => (m.call_id === callId ? { ...m, follow_up_status: status } : m)) };
    try {
      await mutate(
        async () => {
          await patch(`/api/meetings/${callId}`, { status });
          return fetcher<MeetingsResponse>(key);
        },
        { optimisticData: optimistic, rollbackOnError: true, revalidate: false },
      );
      toast(`Marked as ${MEETING_STATUS.find((s) => s.value === status)?.label.toLowerCase()}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't update the meeting", "error");
    } finally {
      setSaving(null);
    }
  }

  if (error) {
    return (
      <Card>
        <EmptyState icon={<CalendarCheck className="h-5 w-5" />} title="Couldn't load meetings" description={error.message} />
      </Card>
    );
  }

  const items = data?.items ?? [];
  const shown = filter === "all" ? items : items.filter((m) => m.follow_up_status === filter);
  const stats = data?.stats;
  const tabs: { value: Filter; label: string; count: number }[] = [
    { value: "all", label: "All", count: items.length },
    ...MEETING_STATUS.map((s) => ({ value: s.value as Filter, label: s.label, count: stats?.by_status[s.value] ?? 0 })),
  ];

  return (
    <>
      <PageHeader title="Meetings" description="Every meeting your agents booked, and how each one went." />
      <div className="flex flex-col gap-6">

      {!data ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<CalendarCheck className="h-5 w-5" />}
            title="No meetings booked yet"
            description="When an agent books a meeting on a call, it shows up here with the time, the contact and a summary of the call. Turn on meeting booking in an agent's settings to get started."
            action={
              <Link href="/agents">
                <Button variant="primary">
                  <Bot className="h-4 w-4" /> Set up booking on an agent
                </Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Booked this week" value={String(stats?.this_week ?? 0)} icon={CalendarDays} hint="Since Monday" />
            <StatCard label="Booked this month" value={String(stats?.this_month ?? 0)} icon={CalendarRange} hint={`${items.length} booked in total`} />
            <StatCard
              label="Show rate"
              value={stats?.show_rate == null ? "—" : `${Math.round(stats.show_rate * 100)}%`}
              icon={UserCheck}
              hint={
                stats?.show_rate == null
                  ? "Mark meetings completed or no-show to see this"
                  : `${stats.by_status.completed} showed up · ${stats.by_status.no_show} no-show${stats.by_status.no_show === 1 ? "" : "s"}`
              }
            />
          </div>

          <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <div className="flex w-max gap-1 rounded-lg bg-zinc-100 p-1" role="tablist" aria-label="Filter meetings">
              {tabs.map((t) => (
                <button
                  key={t.value}
                  role="tab"
                  aria-selected={filter === t.value}
                  onClick={() => setFilter(t.value)}
                  className={cn(
                    "flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    filter === t.value ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-800",
                  )}
                >
                  {t.label}
                  <span className={cn("tabular-nums", filter === t.value ? "text-zinc-500" : "text-zinc-400")}>{t.count}</span>
                </button>
              ))}
            </div>
          </div>

          {shown.length === 0 ? (
            <Card>
              <EmptyState
                icon={<CalendarCheck className="h-5 w-5" />}
                title={`No ${tabs.find((t) => t.value === filter)?.label.toLowerCase()} meetings`}
                description="Change a meeting's status from its card and it will show up under the matching tab."
              />
            </Card>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {shown.map((m) => (
                <MeetingCard key={m.call_id} meeting={m} saving={saving === m.call_id} onStatus={(s) => setStatus(m.call_id, s)} />
              ))}
            </div>
          )}
        </>
      )}
      </div>
    </>
  );
}
