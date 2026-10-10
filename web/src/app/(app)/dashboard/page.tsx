"use client";

import { ArrowRight, Bot, CalendarCheck, CheckCircle2, Circle, Clock, Megaphone, PhoneCall, TrendingUp } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button, Card, CardHeader, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Agent, Call, Overview, SettingsStatus } from "@/lib/types";
import { formatDuration, humanize, timeAgo } from "@/lib/utils";

function Stat({ label, value, icon: Icon, sub }: { label: string; value: string | number; icon: typeof PhoneCall; sub?: string }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-zinc-500">{label}</span>
        <Icon className="h-4 w-4 text-zinc-400" />
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>}
    </Card>
  );
}

function CallsChart({ data }: { data: { date: string; calls: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.calls));
  return (
    <div className="flex h-40 items-end gap-1">
      {data.map((d) => (
        <div key={d.date} className="group relative flex h-full flex-1 items-end">
          <div
            className="w-full rounded-t bg-brand-500/80 transition-colors group-hover:bg-brand-600"
            style={{ height: `${Math.max(d.calls ? 6 : 2, (d.calls / max) * 100)}%`, opacity: d.calls ? 1 : 0.25 }}
          />
          <div className="pointer-events-none absolute -top-8 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-zinc-900 px-2 py-1 text-[11px] text-white group-hover:block">
            {d.date.slice(5)} · {d.calls} calls
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data: overview, error } = useSWR<Overview>("/api/calls/overview?days=30", fetcher, { refreshInterval: 15000 });
  const { data: calls } = useSWR<{ items: Call[] }>("/api/calls/?page_size=8", fetcher, { refreshInterval: 15000 });
  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const { data: status } = useSWR<SettingsStatus>("/api/settings/status", fetcher);

  const steps = [
    { done: !!status?.capabilities.chat_test, label: "Add your OpenAI key", desc: "Unlocks the chat playground and post-call analysis.", href: "/settings" },
    { done: (agents?.length ?? 0) > 0, label: "Create an agent", desc: "Pick a template, write the prompt and knowledge base.", href: "/agents" },
    { done: !!status?.capabilities.web_call, label: "Connect voice (LiveKit, Deepgram, Cartesia)", desc: "Talk to your agent right in the browser.", href: "/settings" },
    { done: !!status?.capabilities.phone_call, label: "Connect a phone line (SIP trunk)", desc: "Let agents dial real numbers and run campaigns.", href: "/settings" },
  ];
  const allDone = steps.every((s) => s.done);

  if (error) {
    return (
      <Card>
        <EmptyState
          icon={<PhoneCall className="h-5 w-5" />}
          title="Can't reach the backend"
          description={`${error.message}. Start it with: cd backend && uvicorn main:app --port 8000`}
        />
      </Card>
    );
  }

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Last 30 days across all agents and campaigns."
        action={
          <Link href="/agents">
            <Button variant="primary">
              <Bot className="h-4 w-4" /> Build an agent
            </Button>
          </Link>
        }
      />

      {!allDone && status && (
        <Card className="mb-6">
          <CardHeader title="Get to your first call" description="Each step unlocks more of the platform. You can test with just step 1 + 2." />
          <div className="grid gap-px bg-zinc-100 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((s, i) => (
              <Link key={s.label} href={s.href} className="flex gap-3 bg-white p-4 hover:bg-zinc-50">
                {s.done ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" /> : <Circle className="h-5 w-5 shrink-0 text-zinc-300" />}
                <div>
                  <div className="text-sm font-medium">
                    {i + 1}. {s.label}
                  </div>
                  <div className="mt-0.5 text-xs text-zinc-500">{s.desc}</div>
                </div>
              </Link>
            ))}
          </div>
        </Card>
      )}

      {!overview ? (
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Total calls" value={overview.total_calls} icon={PhoneCall} sub={`${overview.connected_calls} connected`} />
            <Stat label="Talk time" value={`${overview.total_minutes} min`} icon={Clock} sub={`avg ${formatDuration(overview.avg_duration_seconds)}`} />
            <Stat label="Meetings booked" value={overview.meetings_booked} icon={CalendarCheck} />
            <Stat label="Success rate" value={`${Math.round(overview.success_rate * 100)}%`} icon={TrendingUp} sub="booked, qualified, interested" />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Calls per day" />
              <div className="p-5">
                <CallsChart data={overview.calls_per_day} />
              </div>
            </Card>
            <Card>
              <CardHeader title="Outcomes" />
              <div className="space-y-3 p-5">
                {Object.keys(overview.outcomes).length === 0 && <p className="text-sm text-zinc-500">No calls yet.</p>}
                {Object.entries(overview.outcomes)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => (
                    <div key={k}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span className="text-zinc-600">{humanize(k)}</span>
                        <span className="font-medium">{v}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-zinc-100">
                        <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${(v / Math.max(1, overview.total_calls)) * 100}%` }} />
                      </div>
                    </div>
                  ))}
              </div>
            </Card>
          </div>
        </>
      )}

      <Card className="mt-6">
        <CardHeader
          title="Recent calls"
          action={
            <Link href="/calls" className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          }
        />
        {calls && calls.items.length === 0 ? (
          <EmptyState
            icon={<Megaphone className="h-5 w-5" />}
            title="No calls yet"
            description="Open an agent and hit Test to talk to it, or launch a campaign."
          />
        ) : (
          <div className="divide-y divide-zinc-100">
            {calls?.items.map((c) => (
              <Link key={c.id} href={`/calls/${c.id}`} className="flex items-center gap-4 px-5 py-3 hover:bg-zinc-50">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{c.contact_name || c.to_phone || "Unknown"}</div>
                  <div className="truncate text-xs text-zinc-500">
                    {c.agent_name ?? "—"} {c.campaign_name ? `· ${c.campaign_name}` : ""}
                  </div>
                </div>
                <OutcomeBadge outcome={c.outcome} status={c.status} />
                <span className="hidden w-14 text-right text-xs text-zinc-500 sm:block">{formatDuration(c.duration_seconds)}</span>
                <span className="w-16 text-right text-xs text-zinc-400">{timeAgo(c.started_at)}</span>
              </Link>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
