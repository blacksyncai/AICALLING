"use client";

import { ArrowDownRight, ArrowRight, ArrowUpRight, Bot, CalendarCheck, CheckCircle2, ChevronDown, Circle, Clock, Coins, Megaphone, MessagesSquare, PhoneCall, PhoneIncoming, Users } from "lucide-react";
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


const RANGES = [7, 30, 90] as const;

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** "+12% vs previous 30d" — nothing when the previous period had no activity to compare with. */
function Trend({ now, before, days, invert = false, format = "pct" }: { now: number; before: number; days: number; invert?: boolean; format?: "pct" | "pts" }) {
  if (!before) return null;
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

/** One overview number: label, value, and at most one supporting line plus the trend. */
function OverviewCard({ label, value, icon: Icon, sub, trend, className }: {
  label: string; value: string; icon: typeof PhoneCall; sub?: React.ReactNode; trend?: React.ReactNode; className?: string;
}) {
  return (
    <Card className={cn("flex min-w-0 flex-col p-4 sm:p-5", className)}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-zinc-600 sm:text-sm">{label}</span>
        <span className="hidden h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 sm:flex">
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>
      <div className="mt-2 font-display text-2xl font-semibold tabular-nums tracking-tight sm:text-3xl">{value}</div>
      {sub && <div className="mt-1 text-xs text-zinc-500">{sub}</div>}
      {trend && <div className="mt-1 text-xs">{trend}</div>}
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
  // Running and paused campaigns first, then finished ones; drafts stay collapsed (they live on the Campaigns page).
  const ORDER: Record<string, number> = { running: 0, paused: 1, completed: 2 };
  const allCampaigns = campaigns?.campaigns ?? [];
  const activeCampaigns = allCampaigns
    .filter((c) => c.status in ORDER)
    .sort((a, b) => ORDER[a.status] - ORDER[b.status])
    .slice(0, 4);
  const drafts = allCampaigns.filter((c) => c.status === "draft");

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{greeting()}</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {overview ? `${overview.agents} agent${overview.agents === 1 ? "" : "s"} · ${overview.running_campaigns} campaign${overview.running_campaigns === 1 ? "" : "s"} running` : "Loading your workspace…"}
            <span className="text-zinc-400"> · </span>
            <span className="font-medium text-zinc-700">Showing the last {days} days</span>
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
          <section aria-label="Overview" className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 xl:grid-cols-5">
              <OverviewCard
                label="Calls placed"
                value={overview.total_calls.toLocaleString()}
                icon={PhoneCall}
                sub={
                  overview.browser_tests ? (
                    <Link href={`/calls?call_type=web&days=${days}`} className="hover:text-brand-700">
                      Phone calls · {overview.browser_tests} browser test{overview.browser_tests === 1 ? "" : "s"} not counted
                    </Link>
                  ) : (
                    "Phone calls"
                  )
                }
                trend={<Trend now={overview.total_calls} before={prev.total_calls} days={days} />}
              />
              <OverviewCard
                label="Connected"
                value={overview.connected_calls.toLocaleString()}
                icon={PhoneIncoming}
                sub="Answered or had talk time"
                trend={<Trend now={overview.connected_calls} before={prev.connected_calls} days={days} />}
              />
              <OverviewCard
                label="Meaningful conversations"
                value={overview.meaningful_calls.toLocaleString()}
                icon={MessagesSquare}
                sub={
                  overview.follow_ups ? (
                    <Link href={`/calls?outcome=callback,interested&days=${days}`} className="font-medium text-zinc-900 hover:text-brand-700">
                      {overview.follow_ups.toLocaleString()} follow-up{overview.follow_ups === 1 ? "" : "s"} to work →
                    </Link>
                  ) : (
                    "No follow-ups waiting"
                  )
                }
                trend={<Trend now={overview.meaningful_calls} before={prev.meaningful_calls} days={days} />}
              />
              <OverviewCard
                label="Meetings booked"
                value={overview.meetings_booked.toLocaleString()}
                icon={CalendarCheck}
                sub={
                  <Link href="/meetings" className="hover:text-brand-700">
                    View meetings →
                  </Link>
                }
                trend={<Trend now={overview.meetings_booked} before={prev.meetings_booked} days={days} />}
              />
              <OverviewCard
                label="Talk time"
                value={`${overview.total_minutes.toLocaleString()} min`}
                icon={Clock}
                className="col-span-2 sm:col-span-1"
                sub={overview.connected_calls ? `avg ${formatDuration(overview.avg_duration_seconds)} per connected call` : undefined}
                trend={<Trend now={overview.total_minutes} before={prev.total_minutes} days={days} />}
              />
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-xs text-zinc-500">
              <Users className="h-3.5 w-3.5" />
              <span>
                <span className="font-medium tabular-nums text-zinc-800">{overview.total_leads.toLocaleString()}</span> contact
                {overview.total_leads === 1 ? "" : "s"}
                {overview.new_leads ? ` · ${overview.new_leads.toLocaleString()} added in this period` : ""}
              </span>
              <Link href="/contacts" className="font-medium text-brand-700 hover:text-brand-800">
                {overview.total_leads ? "Open contacts" : "Import contacts"} →
              </Link>
            </div>
          </section>

          <CallPerformance overview={overview} />

          <ActivityHeatmap />

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
                title={drafts.length ? "No campaigns running" : "No campaigns yet"}
                description={drafts.length ? "Start one of your drafts, or create a new campaign." : "Upload a contact list and let an agent call through it."}
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
            {drafts.length > 0 && (
              <details className="group rounded-lg border border-dashed border-zinc-200 px-3 py-2 text-sm">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-zinc-600 marker:hidden">
                  <span>
                    {drafts.length} draft{drafts.length === 1 ? "" : "s"} not started
                  </span>
                  <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                </summary>
                <ul className="mt-2 flex flex-col gap-1">
                  {drafts.slice(0, 5).map((d) => (
                    <li key={d.id}>
                      <Link href={`/campaigns/${d.id}`} className="block truncate rounded-md px-1 py-1 text-zinc-700 hover:bg-zinc-50 hover:text-brand-700">
                        {d.name}
                      </Link>
                    </li>
                  ))}
                  {drafts.length > 5 && (
                    <li>
                      <Link href="/campaigns" className="px-1 text-xs font-medium text-brand-700">
                        All drafts on the Campaigns page →
                      </Link>
                    </li>
                  )}
                </ul>
              </details>
            )}
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
function CallPerformance({ overview }: { overview: Overview }) {
  const pct = (n: number, d: number) => (d > 0 ? (n / d) * 100 : null);
  const calls = overview.total_calls;
  const connected = overview.connected_calls;
  return (
    <section>
      <h3 className="mb-3 font-semibold">Call performance</h3>
      <ScoreCards
        neutral
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
