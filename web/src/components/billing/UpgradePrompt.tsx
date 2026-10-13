"use client";

import { ArrowUpRight, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Modal } from "@/components/ui";

export interface PlanLimitDetail {
  code: "plan_limit";
  feature: string;
  message: string;
  current_plan: string | null;
  limit: number | null;
  used: number | null;
  suggest: { plan: string | null; plan_name: string | null; self_serve: boolean | null; addon: string | null };
}

/** Listens for "plan-limit" (raised by lib/api on a 402 plan_limit) and offers the way forward. */
export function UpgradePrompt() {
  const [detail, setDetail] = useState<PlanLimitDetail | null>(null);
  useEffect(() => {
    const on = (e: Event) => setDetail((e as CustomEvent<PlanLimitDetail>).detail);
    window.addEventListener("plan-limit", on);
    return () => window.removeEventListener("plan-limit", on);
  }, []);
  if (!detail) return null;
  const s = detail.suggest;
  const close = () => setDetail(null);
  return (
    <Modal open onClose={close} title="Your plan doesn't include this yet">
      <div className="space-y-4 text-sm text-zinc-900">
        <div className="flex gap-3 rounded-xl bg-brand-50/70 p-3.5 ring-1 ring-brand-100">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
          <p className="text-zinc-700">{detail.message}</p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={close} className="h-10 rounded-full px-4 text-zinc-600 hover:bg-zinc-100">
            Not now
          </button>
          {s.addon === "agent_slot" && (
            <Link href="/billing?tab=plans#agent-slots" onClick={close} className="inline-flex h-10 items-center rounded-full bg-zinc-100 px-4 font-medium text-zinc-800 hover:bg-zinc-200">
              Add an agent slot · $19/mo
            </Link>
          )}
          {s.plan && (
            <Link
              href={`/billing?tab=plans&plan=${s.plan}`}
              onClick={close}
              className="inline-flex h-10 items-center gap-1.5 rounded-full bg-gradient-to-t from-brand-600 to-brand-500 px-5 font-semibold text-white shadow-sm shadow-brand-500/30"
            >
              {s.self_serve === false ? `Talk to us about ${s.plan_name}` : `See ${s.plan_name}`} <ArrowUpRight className="h-4 w-4" />
            </Link>
          )}
        </div>
      </div>
    </Modal>
  );
}
