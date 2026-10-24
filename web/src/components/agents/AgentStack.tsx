"use client";

/**
 * Agents as a dark stacked list — remixed from the "stacked list" pattern for BlackSync:
 * real agents instead of sample members, lucide icons and our brand colors. Tabs split live agents
 * from drafts (anything not switched on yet), and a draft can be activated right from its row.
 */

import { motion } from "motion/react";
import {
  Briefcase, CalendarCheck, ChevronRight, Copy, Headset, Home, MoreHorizontal, Pin, PinOff, Plus, Power, Search, Sparkles, Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useToast } from "@/components/toast";
import { del, post } from "@/lib/api";
import type { Agent } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";

const ROLES: Record<string, { label: string; icon: typeof Briefcase; cls: string }> = {
  sales_sdr: { label: "Sales SDR", icon: Briefcase, cls: "bg-amber-400/10 text-amber-300 ring-amber-400/20" },
  appointment_setter: { label: "Appointments", icon: CalendarCheck, cls: "bg-sky-400/10 text-sky-300 ring-sky-400/20" },
  real_estate: { label: "Real estate", icon: Home, cls: "bg-emerald-400/10 text-emerald-300 ring-emerald-400/20" },
  receptionist: { label: "Receptionist", icon: Headset, cls: "bg-violet-400/10 text-violet-300 ring-violet-400/20" },
};
const CUSTOM = { label: "Custom", icon: Sparkles, cls: "bg-brand-500/10 text-brand-300 ring-brand-400/20" };

const GRADIENTS = [
  "from-brand-500 to-amber-400", "from-sky-500 to-indigo-500", "from-emerald-500 to-teal-400",
  "from-violet-500 to-fuchsia-500", "from-rose-500 to-orange-400", "from-cyan-500 to-blue-500",
];

const sweep = { type: "spring" as const, stiffness: 400, damping: 35, mass: 0.5 };

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || "A";
}

function gradientFor(id: string) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return GRADIENTS[h % GRADIENTS.length];
}

/** Badge: the agent's specialty ("Expired Listings") when known, else its template's role. */
function roleFor(a: Agent) {
  const base = ROLES[a.template] ?? CUSTOM;
  return a.specialty ? { ...base, label: a.specialty } : base;
}

function matches(a: Agent, q: string) {
  const s = q.trim().toLowerCase();
  if (!s) return true;
  const role = roleFor(a).label;
  return [a.name, a.description, role].some((v) => (v ?? "").toLowerCase().includes(s));
}

function Avatar({ agent, size = "md" }: { agent: Agent; size?: "md" | "sm" }) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br font-semibold text-white ring-2 ring-zinc-950",
        gradientFor(agent.id),
        size === "md" ? "h-11 w-11 text-sm" : "h-9 w-9 text-xs",
      )}
    >
      {initials(agent.name)}
    </span>
  );
}

function RoleBadge({ agent }: { agent: Agent }) {
  const role = roleFor(agent);
  const Icon = role.icon;
  return (
    <span title={role.label} className={cn("inline-flex min-w-0 shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 ring-1 ring-inset", role.cls)}>
      <Icon className="h-3 w-3 shrink-0" />
      <span className="max-w-[110px] truncate text-[11px] font-medium uppercase tracking-wide sm:max-w-[180px]">{role.label}</span>
    </span>
  );
}

function AgentRow({ agent, onChanged }: { agent: Agent; onChanged: () => void }) {
  const toast = useToast();
  const [menu, setMenu] = useState(false);
  const router = useRouter();
  const [activating, setActivating] = useState(false);
  const live = agent.status === "active";
  const calls = agent.stats?.calls ?? 0;

  // Go live; if something still needs fixing, open the agent where it lists them (with "Ignore and launch").
  async function activate() {
    setActivating(true);
    try {
      await post(`/api/agent-builder/agents/${agent.id}/launch`);
      toast(`${agent.name} is live`);
      onChanged();
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.startsWith("Fix these")) router.push(`/agents/${agent.id}?activate=1`);
      else toast(msg, "error");
    } finally {
      setActivating(false);
    }
  }

  return (
    <motion.div
      variants={{ hidden: { opacity: 0, x: 10, y: 15, rotate: 1 }, visible: { opacity: 1, x: 0, y: 0, rotate: 0 } }}
      transition={sweep}
      style={{ originX: 1, originY: 1 }}
      className="group relative flex items-center gap-4 border-b border-white/[0.06] py-3.5 last:border-0"
    >
      <Link href={`/agents/${agent.id}`} className="absolute inset-0 rounded-xl" aria-label={`Open ${agent.name}`} />
      <div className="relative">
        <Avatar agent={agent} />
        {live && (
          <span className="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-zinc-950">
            <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="flex items-center gap-1.5 text-[15px] font-semibold leading-tight tracking-tight text-white group-hover:text-brand-200">
          {agent.pinned && <Pin className="h-3.5 w-3.5 shrink-0 text-brand-300" aria-label="Pinned" />}
          <span className="truncate">{agent.name}</span>
        </h3>
        <div className="mt-1 flex items-center gap-1.5 text-[13px]">
          <span className={cn("h-1.5 w-1.5 rounded-full", live ? "bg-emerald-400" : "bg-amber-400")} />
          <span className={live ? "text-emerald-400" : "text-amber-300"}>{live ? "Live" : "Draft"}</span>
          <span className="truncate text-zinc-500">
            · {calls} {calls === 1 ? "call" : "calls"} · edited {timeAgo(agent.updated_at)}
          </span>
        </div>
      </div>
      <div className="hidden sm:block">
        <RoleBadge agent={agent} />
      </div>
      {!live && (
        <button
          type="button"
          onClick={activate}
          disabled={activating}
          className="relative z-10 inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-emerald-500 px-3 text-xs font-semibold text-white shadow-[0_4px_14px_-4px_rgba(16,185,129,0.7)] transition hover:bg-emerald-400 active:scale-95 disabled:opacity-60"
        >
          <Power className="h-3.5 w-3.5" /> {activating ? "Activating…" : "Activate"}
        </button>
      )}
      <div className="relative z-10">
        <button
          type="button"
          onClick={() => setMenu((v) => !v)}
          className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-white/10 hover:text-white"
          aria-label={`Actions for ${agent.name}`}
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
        {menu && (
          <div
            className="absolute right-0 top-9 z-20 w-40 rounded-xl border border-white/10 bg-zinc-900 py-1 shadow-2xl"
            onMouseLeave={() => setMenu(false)}
          >
            <button
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-zinc-200 hover:bg-white/5"
              onClick={async () => {
                setMenu(false);
                await post(`/api/agents/${agent.id}/pin`, { pinned: !agent.pinned }).catch((e) => toast(e.message, "error"));
                onChanged();
              }}
            >
              {agent.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />} {agent.pinned ? "Unpin" : "Pin to top"}
            </button>
            <button
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-zinc-200 hover:bg-white/5"
              onClick={async () => {
                setMenu(false);
                await post(`/api/agents/${agent.id}/duplicate`).catch((e) => toast(e.message, "error"));
                onChanged();
              }}
            >
              <Copy className="h-4 w-4" /> Duplicate
            </button>
            <button
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-red-500/10"
              onClick={async () => {
                setMenu(false);
                if (!confirm(`Delete "${agent.name}"? Call history is kept.`)) return;
                await del(`/api/agents/${agent.id}`).catch((e) => toast(e.message, "error"));
                onChanged();
              }}
            >
              <Trash2 className="h-4 w-4" /> Delete
            </button>
          </div>
        )}
      </div>
      <ChevronRight className="hidden h-4 w-4 shrink-0 text-zinc-600 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-300 sm:block" />
    </motion.div>
  );
}

function SearchBox({ value, onChange, placeholder, autoFocus }: { value: string; onChange: (v: string) => void; placeholder: string; autoFocus?: boolean }) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="h-11 w-full rounded-2xl border-0 bg-white/[0.05] pl-11 pr-4 text-sm text-white ring-1 ring-inset ring-white/[0.06] transition placeholder:text-zinc-500 focus:bg-white/[0.08] focus:outline-none focus:ring-white/20"
      />
    </div>
  );
}

export type AgentView = "live" | "drafts" | "all";

export function AgentStack({ agents, onChanged, onNew, view, onView }: {
  agents: Agent[]; onChanged: () => void; onNew: () => void; view: AgentView; onView: (v: AgentView) => void;
}) {
  const [query, setQuery] = useState("");
  const liveCount = agents.filter((a) => a.status === "active").length;
  const counts: Record<AgentView, number> = { live: liveCount, drafts: agents.length - liveCount, all: agents.length };
  const shown = useMemo(
    () => agents.filter((a) => (view === "all" || (view === "live") === (a.status === "active")) && matches(a, query)),
    [agents, query, view],
  );
  const tabs: { key: AgentView; label: string }[] = [
    { key: "live", label: "Live" },
    { key: "drafts", label: "Drafts" },
    { key: "all", label: "All" },
  ];

  return (
    <div className="relative mx-auto flex min-h-[480px] w-full max-w-3xl flex-col overflow-hidden rounded-[32px] bg-zinc-950 pb-6 shadow-[0_24px_60px_-24px_rgba(33,27,24,0.55)] ring-1 ring-white/10">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_260px_at_0%_0%,rgba(236,101,60,0.16),transparent_70%)]" />

      <div className="relative p-6 pb-3 sm:p-8 sm:pb-3">
        <div className="mb-5 flex items-center justify-between gap-3">
          <div role="tablist" aria-label="Agents" className="flex rounded-full bg-white/[0.06] p-1 ring-1 ring-inset ring-white/[0.06]">
            {tabs.map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={view === t.key}
                onClick={() => onView(t.key)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition",
                  view === t.key ? "bg-white text-zinc-900 shadow" : "text-zinc-400 hover:text-white",
                )}
              >
                {t.key === "live" && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />}
                {t.key === "drafts" && <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />}
                {t.label}
                <span className={cn("rounded-full px-1.5 text-xs tabular-nums", view === t.key ? "bg-zinc-100 text-zinc-600" : "bg-white/10 text-zinc-400")}>{counts[t.key]}</span>
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={onNew}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-[0_4px_14px_-2px_rgba(236,101,60,0.6)] transition active:scale-95"
            aria-label="New agent"
          >
            <Plus className="h-[18px] w-[18px]" strokeWidth={2.5} />
          </button>
        </div>
        <SearchBox value={query} onChange={setQuery} placeholder={view === "drafts" ? "Search drafts…" : "Search agents…"} />
        {view === "drafts" && counts.drafts > 0 && (
          <p className="mt-3 text-xs text-zinc-500">Drafts aren&apos;t taking calls yet. Test them, then hit Activate to put them live.</p>
        )}
      </div>

      <div className="relative flex-1 px-6 sm:px-8">
        <motion.div key={view} initial="hidden" animate="visible" variants={{ visible: { transition: { staggerChildren: 0.04 } } }}>
          {shown.map((a) => (
            <AgentRow key={a.id} agent={a} onChanged={onChanged} />
          ))}
        </motion.div>
        {shown.length === 0 && (
          <div className="py-10 text-center text-sm text-zinc-500">
            {query ? (
              "No agents match your search."
            ) : view === "live" ? (
              <>
                No live agents yet.{" "}
                {counts.drafts > 0 && (
                  <button type="button" onClick={() => onView("drafts")} className="font-medium text-brand-300 hover:text-brand-200">
                    View your {counts.drafts} draft{counts.drafts === 1 ? "" : "s"} →
                  </button>
                )}
              </>
            ) : (
              "No drafts — every agent is live."
            )}
          </div>
        )}
      </div>
    </div>
  );
}
