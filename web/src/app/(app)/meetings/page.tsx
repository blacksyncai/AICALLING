"use client";

import { Bot, CalendarCheck, CalendarDays, CalendarRange, LayoutGrid, UserCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import useSWR from "swr";
import { GoogleCalendarBar } from "@/components/meetings/GoogleCalendarBar";
import { MeetingCard } from "@/components/meetings/MeetingCard";
import { MeetingsCalendar } from "@/components/meetings/MeetingsCalendar";
import { MeetingTimeModal } from "@/components/meetings/MeetingTimeModal";
import { MEETING_STATUS, type GoogleStatus, type Meeting, type MeetingStatus, type MeetingsResponse } from "@/components/meetings/types";
import { useToast } from "@/components/toast";
import { Button, Card, EmptyState, Modal, PageHeader, Spinner } from "@/components/ui";
import { PillTabs } from "@/components/ui/pricing";
import { fetcher, patch } from "@/lib/api";
import { cn } from "@/lib/utils";

type Filter = "all" | MeetingStatus;
type View = "calendar" | "cards";

const GOOGLE_RESULT: Record<string, [string, "error" | undefined]> = {
  connected: ["Google Calendar connected", undefined],
  cancelled: ["Google Calendar wasn't connected", "error"],
  failed: ["Couldn't connect Google Calendar. Please try again.", "error"],
};

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
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      }
    >
      <Meetings />
    </Suspense>
  );
}

function Meetings() {
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<View>("calendar");
  const [saving, setSaving] = useState<string | null>(null);
  const [timeFor, setTimeFor] = useState<Meeting | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const key = "/api/meetings?status=all";
  const { data, error, mutate } = useSWR<MeetingsResponse>(key, fetcher, { refreshInterval: 30000 });
  const { data: google, mutate: refreshGoogle } = useSWR<GoogleStatus>("/api/calendar/google", fetcher);

  // Back from Google's consent screen: say how it went, then tidy the URL.
  useEffect(() => {
    const r = params.get("google");
    if (!r) return;
    const [msg, tone] = GOOGLE_RESULT[r] ?? GOOGLE_RESULT.failed;
    toast(msg, tone);
    void refreshGoogle();
    router.replace(pathname, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** PATCH a meeting (time and/or status) and refresh the list. Returns false on failure. */
  async function update(callId: string, body: Record<string, unknown>, done?: string): Promise<boolean> {
    try {
      const updated = await patch<Meeting>(`/api/meetings/${callId}`, body);
      await mutate();
      if (updated.calendar_error) toast(`Saved, but Google Calendar wasn't updated: ${updated.calendar_error}`, "error");
      else if (done) toast(done);
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't update the meeting", "error");
      return false;
    }
  }

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
      if (google?.connected) void mutate();
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
  const opened = openId ? items.find((m) => m.call_id === openId) ?? null : null;
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
      <GoogleCalendarBar status={google} onChanged={() => void Promise.all([refreshGoogle(), mutate()])} />

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

          <PillTabs<View>
            value={view}
            onChange={setView}
            layoutId="meetings-view"
            tabs={[
              { value: "calendar", label: "Calendar", icon: <CalendarDays className="h-4 w-4" /> },
              { value: "cards", label: "List", icon: <LayoutGrid className="h-4 w-4" /> },
            ]}
          />

          {view === "calendar" ? (
            <MeetingsCalendar
              meetings={items}
              googleConnected={!!google?.connected}
              onMove={(m, start) => update(m.call_id, { start }, "Meeting moved")}
              onOpen={(m) => setOpenId(m.call_id)}
              onSetTime={setTimeFor}
            />
          ) : (
          <>
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
                <MeetingCard
                  key={m.call_id}
                  meeting={m}
                  saving={saving === m.call_id}
                  onStatus={(s) => setStatus(m.call_id, s)}
                  onSetTime={() => setTimeFor(m)}
                />
              ))}
            </div>
          )}
          </>
          )}
        </>
      )}
      </div>

      <MeetingTimeModal
        meeting={timeFor}
        onClose={() => setTimeFor(null)}
        onSave={async (start, minutes) => {
          if (timeFor) await update(timeFor.call_id, { start, duration_minutes: minutes }, start ? "Meeting time saved" : "Time cleared");
        }}
      />
      <Modal open={!!opened} onClose={() => setOpenId(null)} title="Meeting" wide>
        {opened && (
          <MeetingCard
            meeting={opened}
            saving={saving === opened.call_id}
            onStatus={(s) => setStatus(opened.call_id, s)}
            onSetTime={() => {
              setOpenId(null);
              setTimeFor(opened);
            }}
          />
        )}
      </Modal>
    </>
  );
}
