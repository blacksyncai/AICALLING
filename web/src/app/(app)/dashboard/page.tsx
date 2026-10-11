"use client";

import { ArrowDownRight, ArrowRight, ArrowUpRight, Bot, CalendarCheck, CheckCircle2, Circle, Clock, Coins, Megaphone, MessagesSquare, PhoneCall, PhoneIncoming, Users } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { ActivityHeatmap } from "@/components/dashboard/ActivityHeatmap";
import { GettingStarted } from "@/components/dashboard/GettingStarted";
import { ScoreCards } from "@/components/ui/score-gauge";
import { Badge, Button, Card, EmptyState, Notice, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Agent, Call, Campaign, Overview, SettingsStatus } from "@/lib/types";
import { CAMPAIGN_TONE, OUTCOME_TONE, cn, formatDuration, timeAgo } from "@/lib/utils";

// Recharts measures the DOM, so render the chart on the client only.
const CallVolumeChart = dynamic(() => import("@/components/dashboard/CallVolumeChart").then((m) => m.CallVolumeChart), {
  ssr: false,
  loading: () => <div className="h-64 animate-pulse rounded-lg bg-zinc-100" />,
});

const RANGES = [7, 30, 90] as const;

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** "+12% vs previous 30 days" — or a neutral note when there's nothing to compare. */
function Trend({ now, before, days, invert = false, format = "pct" }: { now: number; before: number; days: number; invert?: boolean; format?: "pct" | "pts" }) {
  if (!before && !now) return <span className="text-zinc-400">No activity yet</span>;
  if (!before) return <span className="text-zinc-500">New this period</span>;
  const delta = format === "pts" ? (now - before) * 100 : ((now - before) / before) * 100;
  const rounded = Math.round(delta);
  if (rounded === 0) return <span className="text-zinc-500">Flat vs previous {days}d</span>;
  const good = invert ? rounded < 0 : rounded > 0;
  const Icon = rounded > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-medium", good ? "text-emerald-700" : "text-red-600")}>
      <Icon className="h-3.5 w-3.5" />
      {rounded > 0 ? "+" : ""}
      {rounded}
      {format === "pts" ? " pts" : "%"}
      <span className="ml-1 font-normal text-zinc-500">vs previous {days}d</span>
    </span>
  );
}

function StatCard({ label, value, icon: Icon, children }: { label: string; value: string; icon: typeof PhoneCall; children: React.ReactNode }) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <span className="text-sm font-medium text-zinc-600">{label}</span>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 font-display text-3xl font-semibold tabular-nums tracking-tight">{value}</div>
      <div className="mt-1 text-xs">{children}</div>
    </Card>
  );
}

const ACTIVITY_VERB: Record<string, string> = {
  meeting_booked: "booked a meeting",
  qualified: "was qualified",
  interested: "showed interest",
  not_interested: "wasn't interested",
  not_qualified: "wasn't a fit",
  callback: "asked for a callback",
  transferred: "was transferred to your team",
  voicemail: "went to voicemail",
  no_answer: "didn't pick up",
  completed: "finished a call",
  failed: "call failed",
};

const AVATAR_TONES = ["bg-orange-100 text-orange-800", "bg-amber-100 text-amber-800", "bg-stone-200 text-stone-700", "bg-rose-100 text-rose-800", "bg-emerald-100 text-emerald-800"];

function initials(name: string) {
  const parts = name.replace(/[^A-Za-z0-9 +]/g, " ").trim().split(/\s+/);
  if (parts[0]?.startsWith("+")) return "#";
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function ContactAvatar({ name }: { name: string }) {
  const tone = AVATAR_TONES[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_TONES.length];
  return <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold", tone)}>{initials(name)}</span>;
}

export default function DashboardPage() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const { data: overview, error } = useSWR<Overview>(`/api/calls/overview?days=${days}`, fetcher, { refreshInterval: 15000 });
  const { data: calls } = useSWR<{ items: Call[] }>("/api/calls/?page_size=7", fetcher, { refreshInterval: 15000 });
  const { data: campaigns } = useSWR<{ campaigns: Campaign[] }>("/api/campaigns/", fetcher, { refreshInterval: 15000 });
  const { data: agents } = useSWR<Agent[]>("/api/agents/", fetcher);
  const { data: status } = useSWR<SettingsStatus>("/api/settings/status", fetcher);
  const { session } = useSession();
  // Platform keys are configured by the BlackSync admin, so only they see the setup checklist.
  const isPlatformAdmin = !!session?.user.is_superadmin && !session.impersonating;

  const steps = [
    { done: !!status?.capabilities.chat_test, label: "Connect OpenAI", href: "/settings" },
    { done: (agents?.length ?? 0) > 0, label: "Create an agent", href: "/agents" },
    { done: !!status?.capabilities.web_call, label: "Connect voice", href: "/settings" },
    { done: !!status?.capabilities.phone_call, label: "Connect a phone line", href: "/settings" },
  ];
  const setupLeft = steps.filter((s) => !s.done).length;

  if (error) {
    return (
      <Card>
        <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="Can't reach the backend" description={error.message} />
      </Card>
    );
  }

  const prev = overview?.previous;
  const activeCampaigns = (campaigns?.campaigns ?? []).filter((c) => c.status !== "cancelled").slice(0, 4);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{greeting()}</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {overview ? `${overview.agents} agent${overview.agents === 1 ? "" : "s"} · ${overview.running_campaigns} campaign${overview.running_campaigns === 1 ? "" : "s"} running` : "Loading your workspace…"}
          </p>
        </div>
        <div className="flex items-center gap-2">
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
          <Link href="/agents">
            <Button variant="primary">
              <Bot className="h-4 w-4" /> New agent
            </Button>
          </Link>
        </div>
      </div>

      {/* Getting started (new accounts) */}
      <GettingStarted />

      {/* Setup strip */}
      {isPlatformAdmin && status && setupLeft > 0 && (
        <Card className="flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
          <div className="text-sm font-medium">
            Finish setup <span className="text-zinc-500">· {4 - setupLeft}/4 done</span>
          </div>
          <div className="flex flex-1 flex-wrap gap-x-5 gap-y-2">
            {steps.map((s) => (
              <Link key={s.label} href={s.href} className={cn("flex items-center gap-1.5 text-sm", s.done ? "text-zinc-500" : "text-zinc-900 hover:text-brand-700")}>
                {s.done ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Circle className="h-4 w-4 text-zinc-300" />}
                {s.label}
              </Link>
            ))}
          </div>
        </Card>
      )}

      {overview && !overview.unlimited_credits && overview.credits_balance <= 10 && (
        <Notice tone={overview.credits_balance <= 0 ? "red" : "amber"}>
          <span className="flex items-center gap-2 text-sm">
            <Coins className="h-4 w-4 shrink-0" />
            {overview.credits_balance <= 0
              ? "You're out of calling credits — phone calls and campaigns are paused until more are added."
              : `Only ${overview.credits_balance} calling credit${overview.credits_balance === 1 ? "" : "s"} left (1 credit = 1 minute).`}{" "}
            <Link href="/billing?tab=credits" className="font-medium underline">View credits</Link>
          </span>
        </Notice>
      )}

      {/* Stats */}
      {!overview || !prev ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <StatCard label="Total leads" value={overview.total_leads.toLocaleString()} icon={Users}>
              {overview.new_leads ? (
                <span className="text-zinc-500">
                  <span className="font-medium text-emerald-700">+{overview.new_leads.toLocaleString()}</span> added in the last {days}d
                </span>
              ) : (
                <Link href="/contacts" className="text-zinc-500 hover:text-brand-700">Import contacts →</Link>
              )}
            </StatCard>
            <StatCard label="Calls placed" value={overview.total_calls.toLocaleString()} icon={PhoneCall}>
              <Trend now={overview.total_calls} before={prev.total_calls} days={days} />
            </StatCard>
            <StatCard label="Connect rate" value={`${Math.round(overview.connect_rate * 100)}%`} icon={PhoneIncoming}>
              <Trend now={overview.connect_rate} before={prev.connect_rate} days={days} format="pts" />
            </StatCard>
            <StatCard label="Meaningful conversations" value={overview.meaningful_calls.toLocaleString()} icon={MessagesSquare}>
              <span className="text-zinc-500">
                <Link href="/contacts?status=callback" className="font-medium text-zinc-900 hover:text-brand-700">
                  {overview.follow_ups.toLocaleString()} follow-up{overview.follow_ups === 1 ? "" : "s"}
                </Link>{" "}
                to work · <Trend now={overview.meaningful_calls} before={prev.meaningful_calls} days={days} />
              </span>
            </StatCard>
            <StatCard label="Meetings booked" value={overview.meetings_booked.toLocaleString()} icon={CalendarCheck}>
              <Trend now={overview.meetings_booked} before={prev.meetings_booked} days={days} />
            </StatCard>
            <StatCard label="Talk time" value={`${overview.total_minutes.toLocaleString()} min`} icon={Clock}>
              <span className="text-zinc-500">avg {formatDuration(overview.avg_duration_seconds)} per connected call</span>
            </StatCard>
          </div>

          <CallPerformance overview={overview} days={days} />

          <ActivityHeatmap />

          <Card>
            <div className="flex flex-wrap items-start justify-between gap-2 px-5 pt-5">
              <div>
                <h3 className="font-semibold">Call volume</h3>
                <p className="text-sm text-zinc-500">Dialed, connected and booked per day, last {days} days</p>
              </div>
              <div className="text-right text-xs text-zinc-500">
                Success rate <span className="ml-1 font-display text-base font-semibold text-zinc-900">{Math.round(overview.success_rate * 100)}%</span>
              </div>
            </div>
            <div className="p-5 pt-4">
              <CallVolumeChart data={overview.calls_per_day} />
            </div>
          </Card>
        </>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Campaigns */}
        <Card className="min-w-0">
          <div className="flex items-start justify-between gap-2 px-5 pt-5">
            <div>
              <h3 className="font-semibold">Campaigns</h3>
              <p className="text-sm text-zinc-500">Progress through each contact list</p>
            </div>
            <Link href="/campaigns" className="flex shrink-0 items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
              All campaigns <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="flex flex-col gap-5 p-5">
            {campaigns && activeCampaigns.length === 0 && (
              <EmptyState
                icon={<Megaphone className="h-5 w-5" />}
                title="No campaigns yet"
                description="Upload a contact list and let an agent call through it."
                action={
                  <Link href="/campaigns">
                    <Button size="sm">Create a campaign</Button>
                  </Link>
                }
              />
            )}
            {activeCampaigns.map((c) => {
              const pct = c.total_targets ? Math.min(100, Math.round((c.total_dialed / c.total_targets) * 100)) : 0;
              const agentName = agents?.find((a) => a.id === c.agent_id)?.name;
              return (
                <Link key={c.id} href={`/campaigns/${c.id}`} className="group flex min-w-0 flex-col gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium group-hover:text-brand-700">{c.name}</span>
                    <Badge tone={CAMPAIGN_TONE[c.status]}>{c.status}</Badge>
                  </div>
                  <p className="truncate text-xs text-zinc-500">
                    {agentName ?? "No agent"} · {c.total_targets} contacts
                  </p>
                  <div className="flex items-center gap-3">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${c.name} progress`}>
                      <div className="h-full rounded-full brand-gradient transition-all" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-10 shrink-0 text-right text-xs tabular-nums text-zinc-500">{pct}%</span>
                  </div>
                  <div className="flex gap-4 text-xs text-zinc-500">
                    <span>
                      <span className="font-medium text-zinc-900 tabular-nums">{c.total_dialed}</span> dialed
                    </span>
                    <span>
                      <span className="font-medium text-zinc-900 tabular-nums">{c.total_qualified}</span> qualified
                    </span>
                    <span>
                      <span className="font-medium text-zinc-900 tabular-nums">{c.total_booked}</span> booked
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        </Card>

        {/* Activity */}
        <Card className="min-w-0">
          <div className="flex items-start justify-between gap-2 px-5 pt-5">
            <div>
              <h3 className="font-semibold">Recent activity</h3>
              <p className="text-sm text-zinc-500">What your agents just did</p>
            </div>
            <Link href="/calls" className="flex shrink-0 items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
              Call logs <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <ol className="flex flex-col p-3">
            {calls && calls.items.length === 0 && (
              <EmptyState icon={<PhoneCall className="h-5 w-5" />} title="No calls yet" description="Open an agent and test it, or start a campaign." />
            )}
            {calls?.items.map((c) => {
              const who = c.contact_name || c.to_phone || "Unknown";
              const live = !c.outcome && ["initiated", "ringing", "connected"].includes(c.status);
              const verb = live ? "is on a call" : ACTIVITY_VERB[c.outcome ?? ""] ?? "finished a call";
              return (
                <li key={c.id}>
                  <Link href={`/calls/${c.id}`} className="flex items-start gap-3 rounded-lg px-2 py-2.5 hover:bg-zinc-50">
                    <ContactAvatar name={who} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-snug">
                        <span className="font-medium">{who}</span> <span className="text-zinc-500">{verb}</span>
                      </p>
                      <p className="truncate text-xs text-zinc-500">
                        {c.agent_name ?? "Agent"}
                        {c.campaign_name ? ` · ${c.campaign_name}` : ""} · {timeAgo(c.started_at)}
                      </p>
                    </div>
                    {c.outcome ? (
                      <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", { green: "bg-emerald-500", blue: "bg-blue-500", amber: "bg-amber-500", red: "bg-red-500", violet: "bg-violet-500", gray: "bg-zinc-300" }[OUTCOME_TONE[c.outcome] ?? "gray"])} />
                    ) : (
                      live && <span className="mt-1 h-2 w-2 shrink-0 animate-pulse rounded-full bg-brand-500" />
                    )}
                  </Link>
                </li>
              );
            })}
          </ol>
        </Card>
      </div>
    </div>
  );
}


/** Three gauges built from the same period's numbers: answered, real conversations, booked. */
function CallPerformance({ overview, days }: { overview: Overview; days: number }) {
  const pct = (n: number, d: number) => (d > 0 ? (n / d) * 100 : null);
  const calls = overview.total_calls;
  const connected = overview.connected_calls;
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">Call performance</h3>
        <span className="text-xs text-zinc-500">Last {days} days</span>
      </div>
      <ScoreCards
        items={[
          {
            title: "Connect rate",
            value: pct(connected, calls),
            target: 30,
            caption: calls ? `${connected.toLocaleString()} of ${calls.toLocaleString()} calls answered` : undefined,
            description: "How often someone picks up. Calling at better times and fresh lists move this most.",
            action: calls ? { label: "See call logs", href: "/calls" } : { label: "Start a campaign", href: "/campaigns" },
          },
          {
            title: "Conversation rate",
            value: pct(overview.meaningful_calls, connected),
            target: 50,
            caption: connected ? `${overview.meaningful_calls.toLocaleString()} of ${connected.toLocaleString()} answered calls` : undefined,
            description: "Answered calls that became a real conversation. A strong opening keeps people on the line.",
            action: { label: "Improve your agent", href: "/agents" },
          },
          {
            title: "Booking rate",
            value: pct(overview.meetings_booked, connected),
            target: 10,
            caption: connected ? `${overview.meetings_booked.toLocaleString()} booked from ${connected.toLocaleString()} answered` : undefined,
            description: "Answered calls that ended with a meeting on the calendar.",
            action: { label: "View meetings", href: "/meetings" },
          },
        ]}
      />
    </section>
  );
}
