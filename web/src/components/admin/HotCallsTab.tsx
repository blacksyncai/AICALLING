"use client";

import { ArrowUpRight, Clock, Flame, PhoneCall } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { Badge, Button, Card, EmptyState, Select, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { switchOrg } from "@/lib/session";
import { cn, timeAgo } from "@/lib/utils";

type Group = "all" | "booked" | "hot" | "callback";

interface HotCall {
  id: string;
  account: { id: string; name: string };
  name: string;
  company: string;
  phone: string | null;
  outcome: string;
  label: string;
  quote: string;
  summary: string;
  next_action: string | null;
  timeline: string | null;
  meeting_time: string | null;
  booking_status: string | null;
  agent: string | null;
  call_type: string;
  duration_seconds: number;
  started_at: string | null;
}

interface HotCalls {
  items: HotCall[];
  counts: Record<Exclude<Group, "all">, number>;
  days: number;
}

const TONE: Record<string, "green" | "brand" | "violet" | "amber" | "blue"> = {
  meeting_booked: "green",
  interested: "brand",
  qualified: "brand",
  information_requested: "blue",
  transferred: "violet",
  callback: "amber",
  potential_follow_up: "amber",
};

const GROUPS: { value: Group; label: string }[] = [
  { value: "all", label: "All" },
  { value: "booked", label: "Booked" },
  { value: "hot", label: "Interested" },
  { value: "callback", label: "Call back / follow up" },
];

/** "1m 05s", "48s": how long the call lasted. */
function callLength(seconds: number): string {
  const s = Math.max(0, Math.round(seconds || 0));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** Admin → Hot calls: every account's calls where the transcript shows real intent, newest first. */
export function HotCallsTab() {
  const [group, setGroup] = useState<Group>("all");
  const [days, setDays] = useState(7);
  const [tests, setTests] = useState(false);
  const { data, error } = useSWR<HotCalls>(
    `/api/admin/hot-calls?days=${days}&group=${group}&include_tests=${tests}`,
    fetcher,
    { refreshInterval: 60000, keepPreviousData: true },
  );

  const total = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {GROUPS.map((g) => {
          const n = g.value === "all" ? total : data?.counts[g.value];
          return (
            <button
              key={g.value}
              onClick={() => setGroup(g.value)}
              className={cn(
                "rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition",
                group === g.value ? "bg-zinc-900 text-white ring-zinc-900" : "bg-white text-zinc-700 ring-zinc-200 hover:bg-zinc-50",
              )}
            >
              {g.label}
              {group === "all" && n !== undefined ? <span className="ml-1.5 opacity-70">{n}</span> : null}
            </button>
          );
        })}
        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-zinc-600">
            <input type="checkbox" checked={tests} onChange={(e) => setTests(e.target.checked)} className="rounded border-zinc-300" />
            Include test calls
          </label>
          <Select value={String(days)} onChange={(e) => setDays(Number(e.target.value))} aria-label="Time range" className="w-36">
            <option value="1">Last 24 hours</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
          </Select>
        </div>
      </div>

      {error ? (
        <Card>
          <EmptyState icon={<Flame className="h-5 w-5" />} title="Couldn't load calls" description={error.message} />
        </Card>
      ) : !data ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Flame className="h-5 w-5" />}
            title="No hot calls yet"
            description="Calls where someone books, shows interest or asks for a callback show up here."
          />
        </Card>
      ) : (
        <Card className="divide-y divide-zinc-100 overflow-hidden p-0">
          {data.items.map((c) => (
            <HotCallRow key={c.id} call={c} />
          ))}
        </Card>
      )}
    </div>
  );
}

function HotCallRow({ call: c }: { call: HotCall }) {
  const [opening, setOpening] = useState(false);
  const unconfirmed = c.booking_status === "failed" || c.booking_status === "tentative";
  return (
    <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-zinc-900">{c.name}</span>
          {c.company && <span className="text-zinc-500">· {c.company}</span>}
          <Badge tone={TONE[c.outcome] ?? "gray"}>{c.label}</Badge>
          {unconfirmed && <Badge tone="amber">Not on calendar</Badge>}
          {c.call_type === "web" && <Badge>Test</Badge>}
        </div>
        {c.quote && <p className="mt-1.5 text-sm italic text-zinc-800">&ldquo;{c.quote}&rdquo;</p>}
        {c.summary && <p className="mt-1 line-clamp-2 text-sm text-zinc-500">{c.summary}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
          <span className="font-medium text-zinc-700">{c.account.name}</span>
          {c.agent && <span>{c.agent}</span>}
          {c.meeting_time && <span>Meeting: {c.meeting_time}</span>}
          {!c.meeting_time && c.timeline && <span>When: {c.timeline}</span>}
          {c.phone && (
            <span className="inline-flex items-center gap-1">
              <PhoneCall className="h-3 w-3" />
              {c.phone}
            </span>
          )}
          <span className="inline-flex items-center gap-1 font-medium text-zinc-700">
            <Clock className="h-3 w-3" />
            {callLength(c.duration_seconds)}
          </span>
          {c.started_at && <span>{timeAgo(c.started_at)}</span>}
        </div>
      </div>
      <Button
        size="sm"
        disabled={opening}
        onClick={async () => {
          setOpening(true);
          await switchOrg(c.account.id, `/calls/${c.id}`);
        }}
      >
        Open call <ArrowUpRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
