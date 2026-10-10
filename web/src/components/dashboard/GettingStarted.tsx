"use client";

import { ArrowRight, Bot, Check, Megaphone, Rocket, Upload, UserPlus, Headphones, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Card } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

type AgentLite = { id: string; created_at?: string | null; updated_at?: string | null };
type Paged = { total: number };
type CampaignsLite = { campaigns: { id: string; status: string }[] };
type TeamLite = { members: unknown[]; invites: unknown[] };

type Step = {
  key: string;
  title: string;
  body: string;
  cta: string;
  href: string;
  icon: LucideIcon;
  done: boolean;
};

const storageKey = (orgId: string) => `blacksync:getting-started-hidden:${orgId}`;

function readHidden(orgId: string): boolean {
  try {
    return window.localStorage.getItem(storageKey(orgId)) === "1";
  } catch {
    return false;
  }
}

function writeHidden(orgId: string) {
  try {
    window.localStorage.setItem(storageKey(orgId), "1");
  } catch {
    /* private mode or storage blocked — hiding still works for this visit */
  }
}

/** A five-step checklist for new accounts, worked out from what's already set up. */
export function GettingStarted({ className }: { className?: string }) {
  const { session } = useSession();
  const orgId = session?.org?.id;
  const [hidden, setHidden] = useState<boolean | null>(null);

  useEffect(() => {
    if (orgId) setHidden(readHidden(orgId));
  }, [orgId]);

  const on = !!orgId && hidden === false;
  const opts = { revalidateOnFocus: true, shouldRetryOnError: false };
  const agents = useSWR<AgentLite[]>(on ? "/api/agents/" : null, fetcher, opts);
  const webCalls = useSWR<Paged>(on ? "/api/calls/?call_type=web&page_size=1" : null, fetcher, opts);
  const contacts = useSWR<Paged>(on ? "/api/contacts?page_size=1" : null, fetcher, opts);
  const campaigns = useSWR<CampaignsLite>(on ? "/api/campaigns/" : null, fetcher, opts);
  const team = useSWR<TeamLite>(on ? "/api/account/org" : null, fetcher, opts);

  const all = [agents, webCalls, contacts, campaigns, team];
  // Wait until every check has answered (or failed) so the card doesn't flicker in and out.
  const settled = all.every((r) => r.data !== undefined || r.error !== undefined);
  if (!on || !settled) return null;

  const steps: Step[] = [
    {
      key: "agent",
      title: "Create or customize an agent",
      body: "Give your AI caller a name, a voice and a script that sounds like your team.",
      cta: "Open agents",
      href: "/agents",
      icon: Bot,
      done: (agents.data?.length ?? 0) > 0,
    },
    {
      key: "test",
      title: "Test your agent",
      body: "Talk to it from your browser to hear exactly what your prospects will hear.",
      cta: "Try a test call",
      href: agents.data?.[0] ? `/agents/${agents.data[0].id}` : "/agents",
      icon: Headphones,
      done: (webCalls.data?.total ?? 0) > 0,
    },
    {
      key: "contacts",
      title: "Import your contacts",
      body: "Upload a spreadsheet of the people you want to reach.",
      cta: "Import contacts",
      href: "/contacts",
      icon: Upload,
      done: (contacts.data?.total ?? 0) > 0,
    },
    {
      key: "campaign",
      title: "Launch a campaign",
      body: "Pick an agent and a list, and let it start calling for you.",
      cta: "Create a campaign",
      href: "/campaigns",
      icon: Megaphone,
      done: (campaigns.data?.campaigns ?? []).some((c) => ["running", "completed", "paused"].includes(c.status)),
    },
    {
      key: "team",
      title: "Invite your team",
      body: "Bring in teammates so everyone can follow up on booked meetings.",
      cta: "Invite teammates",
      href: "/profile?tab=team",
      icon: UserPlus,
      done: (team.data?.members.length ?? 0) > 1 || (team.data?.invites.length ?? 0) > 0,
    },
  ];

  const doneCount = steps.filter((s) => s.done).length;
  if (doneCount === steps.length) return null;
  const nextKey = steps.find((s) => !s.done)?.key;
  const pct = Math.round((doneCount / steps.length) * 100);

  const hide = () => {
    if (orgId) writeHidden(orgId);
    setHidden(true);
  };

  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="flex items-start gap-3 px-5 pt-5">
        <span className="brand-gradient flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white shadow-sm">
          <Rocket className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-zinc-900">Get your first calls going</h2>
          <p className="mt-0.5 text-xs text-zinc-500">A few quick steps and your AI caller is booking meetings.</p>
        </div>
        <button
          type="button"
          onClick={hide}
          className="-mr-1 -mt-1 flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800"
          aria-label="Hide getting started checklist"
        >
          <X className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Hide</span>
        </button>
      </div>

      <div className="px-5 pb-4 pt-4">
        <div className="mb-1.5 flex items-center justify-between text-xs">
          <span className="font-medium text-zinc-700">
            {doneCount} of {steps.length} done
          </span>
          <span className="tabular-nums text-zinc-400">{pct}%</span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-zinc-100"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={steps.length}
          aria-valuenow={doneCount}
          aria-label="Getting started progress"
        >
          <div className="brand-gradient h-full rounded-full transition-[width] duration-500" style={{ width: `${Math.max(pct, 4)}%` }} />
        </div>
      </div>

      <ol className="divide-y divide-zinc-100 border-t border-zinc-100">
        {steps.map((s, i) => {
          const isNext = s.key === nextKey;
          const Icon = s.icon;
          return (
            <li key={s.key} className={cn("flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5", isNext && "bg-brand-50/40")}>
              <div className="flex min-w-0 flex-1 basis-60 items-start gap-3">
                <span
                  className={cn(
                    "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                    s.done ? "bg-emerald-500 text-white" : isNext ? "border-2 border-brand-500 text-brand-700" : "border border-zinc-300 text-zinc-400",
                  )}
                  aria-hidden
                >
                  {s.done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
                </span>
                <div className="min-w-0">
                  <p className={cn("flex items-center gap-1.5 text-sm font-medium", s.done ? "text-zinc-400 line-through decoration-zinc-300" : "text-zinc-900")}>
                    <Icon className={cn("h-3.5 w-3.5 shrink-0", s.done ? "text-zinc-300" : "text-zinc-400")} />
                    {s.title}
                    <span className="sr-only">{s.done ? " (done)" : ""}</span>
                  </p>
                  {!s.done && <p className="mt-0.5 text-xs text-zinc-500">{s.body}</p>}
                </div>
              </div>
              {!s.done && (
                <Link
                  href={s.href}
                  className={cn(
                    "ml-9 inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 sm:ml-0",
                    isNext ? "bg-brand-600 text-white hover:bg-brand-700" : "border border-zinc-200 bg-white text-zinc-800 hover:bg-zinc-50",
                  )}
                >
                  {s.cta}
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
