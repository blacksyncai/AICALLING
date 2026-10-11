"use client";

import { ArrowRight, Sparkles, UserCheck, UserSearch, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Card } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { BuilderCatalog } from "@/lib/builder";
import { useSession } from "@/lib/session";

const key = (orgId: string) => `blacksync:recommended-hidden:${orgId}`;

/** From the free-trial answers: agents to build for their industry, Lead Finder where it fits, and expert help. */
export function RecommendedForYou() {
  const { session } = useSession();
  const org = session?.org;
  const [hidden, setHidden] = useState<boolean | null>(null);
  useEffect(() => {
    if (!org?.id) return;
    try {
      setHidden(window.localStorage.getItem(key(org.id)) === "1");
    } catch {
      setHidden(false);
    }
  }, [org?.id]);
  const on = hidden === false && !!org?.industry;
  const { data: catalog } = useSWR<BuilderCatalog>(on ? "/api/agent-builder/catalog" : null, fetcher, { revalidateOnFocus: false });
  if (!on || !org || !catalog) return null;

  const industry = catalog.industries.find((i) => i.key === org.industry);
  const all = catalog.specialties?.[org.industry!] ?? catalog.specialties?.other ?? [];
  const chosen = org.onboarding?.goals ?? [];
  // Their picks first, then the rest of the industry's specialties, three in total.
  const picks = [...all.filter((s) => chosen.includes(s.key)), ...all.filter((s) => !chosen.includes(s.key))].slice(0, 3);

  function hide() {
    try {
      window.localStorage.setItem(key(org!.id), "1");
    } catch {
      /* storage blocked */
    }
    setHidden(true);
  }

  const tile = "group flex min-w-0 flex-col justify-between gap-3 rounded-2xl p-4 ring-1 ring-inset transition";
  return (
    <Card className="overflow-hidden">
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-900">Recommended for {industry?.label ?? "you"}</h2>
          <p className="mt-0.5 text-xs text-zinc-500">Based on what you told us. Each one builds in a few minutes with AI.</p>
        </div>
        <button type="button" onClick={hide} className="-mr-1 -mt-1 rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" aria-label="Hide recommendations">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">
        {picks.map((s) => (
          <Link key={s.key} href={`/agents/new?specialty=${encodeURIComponent(s.key)}`} className={`${tile} bg-brand-50/50 ring-brand-100 hover:ring-brand-300`}>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm">
              <Sparkles className="h-4 w-4" />
            </span>
            <span>
              <span className="block text-sm font-semibold text-zinc-900">{s.label}</span>
              <span className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-700">
                Build this agent <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
              </span>
            </span>
          </Link>
        ))}
        {org.lead_finder_enabled !== false && ["real_estate", "home_services"].includes(org.industry ?? "") ? (
          <Link href="/lead-finder" className={`${tile} bg-white ring-zinc-900/[0.06] hover:ring-zinc-300`}>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-900 text-white">
              <UserSearch className="h-4 w-4" />
            </span>
            <span>
              <span className="block text-sm font-semibold text-zinc-900">Find property owners</span>
              <span className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-zinc-600">
                Open Lead Finder <ArrowRight className="h-3 w-3" />
              </span>
            </span>
          </Link>
        ) : (
          <Link href="/agents/expert" className={`${tile} bg-white ring-zinc-900/[0.06] hover:ring-zinc-300`}>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-900 text-white">
              <UserCheck className="h-4 w-4" />
            </span>
            <span>
              <span className="block text-sm font-semibold text-zinc-900">Have an expert build it</span>
              <span className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-zinc-600">
                Book a 15-minute call <ArrowRight className="h-3 w-3" />
              </span>
            </span>
          </Link>
        )}
      </div>
    </Card>
  );
}
