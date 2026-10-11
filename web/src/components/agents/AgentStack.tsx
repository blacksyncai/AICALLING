"use client";

/**
 * Agents as a dark stacked list — remixed from the "stacked list" pattern for BlackSync:
 * real agents instead of sample members, lucide icons, our brand colors, and a bottom
 * "directory" bar that springs open into the full (searchable) list incl. paused agents.
 */

import { AnimatePresence, motion } from "motion/react";
import {
  Briefcase, CalendarCheck, ChevronRight, Copy, Headset, Home, MoreHorizontal, Plus, Search, Sparkles, Trash2, Users, X,
} from "lucide-react";
import Link from "next/link";
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

function matches(a: Agent, q: string) {
  const s = q.trim().toLowerCase();
  if (!s) return true;
  const role = (ROLES[a.template] ?? CUSTOM).label;
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
  const role = ROLES[agent.template] ?? CUSTOM;
  const Icon = role.icon;
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 ring-1 ring-inset", role.cls)}>
      <Icon className="h-3 w-3" />
      <span className="max-w-[90px] truncate text-[11px] font-medium uppercase tracking-wide sm:max-w-none">{role.label}</span>
    </span>
  );
}

function AgentRow({ agent, onChanged }: { agent: Agent; onChanged: () => void }) {
  const toast = useToast();
  const [menu, setMenu] = useState(false);
  const live = agent.status === "active";
  const calls = agent.stats?.calls ?? 0;

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
        <h3 className="truncate text-[15px] font-semibold leading-tight tracking-tight text-white group-hover:text-brand-200">{agent.name}</h3>
        <div className="mt-1 flex items-center gap-1.5 text-[13px]">
          {live && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />}
          <span className={live ? "text-emerald-400" : "text-zinc-500"}>{live ? "Live" : "Paused"}</span>
          <span className="truncate text-zinc-500">
            · {calls} {calls === 1 ? "call" : "calls"} · edited {timeAgo(agent.updated_at)}
          </span>
        </div>
      </div>
      <div className="hidden sm:block">
        <RoleBadge agent={agent} />
      </div>
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

export function AgentStack({ agents, onChanged, onNew }: { agents: Agent[]; onChanged: () => void; onNew: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [dirQuery, setDirQuery] = useState("");

  const live = useMemo(() => agents.filter((a) => a.status === "active" && matches(a, query)), [agents, query]);
  const liveCount = agents.filter((a) => a.status === "active").length;
  const directory = useMemo(() => agents.filter((a) => matches(a, dirQuery)), [agents, dirQuery]);

  return (
    <div className="relative mx-auto flex min-h-[560px] w-full max-w-3xl flex-col overflow-hidden rounded-[32px] bg-zinc-950 pb-24 shadow-[0_24px_60px_-24px_rgba(33,27,24,0.55)] ring-1 ring-white/10">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_260px_at_0%_0%,rgba(236,101,60,0.16),transparent_70%)]" />

      <div className="relative p-6 pb-3 sm:p-8 sm:pb-3">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="flex items-center gap-2 font-display text-lg font-semibold tracking-tight text-white">
            Live agents
            <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs font-normal text-zinc-300">{liveCount}</span>
          </h2>
          <button
            type="button"
            onClick={onNew}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-[0_4px_14px_-2px_rgba(236,101,60,0.6)] transition active:scale-95"
            aria-label="New agent"
          >
            <Plus className="h-[18px] w-[18px]" strokeWidth={2.5} />
          </button>
        </div>
        <SearchBox value={query} onChange={setQuery} placeholder="Search agents…" />
      </div>

      <div className="relative flex-1 px-6 sm:px-8">
        <motion.div initial="hidden" animate="visible" variants={{ visible: { transition: { staggerChildren: 0.04 } } }}>
          {live.map((a) => (
            <AgentRow key={`live-${a.id}`} agent={a} onChanged={onChanged} />
          ))}
        </motion.div>
        {live.length === 0 && (
          <p className="py-10 text-center text-sm text-zinc-500">
            {query ? "No live agents match your search." : "No live agents — open the directory below to switch one on."}
          </p>
        )}
      </div>

      {/* Directory: a bar that springs open into the full list. */}
      <motion.div
        initial={false}
        animate={{
          height: expanded ? "calc(100% - 20px)" : "68px",
          width: expanded ? "calc(100% - 20px)" : "calc(100% - 40px)",
          bottom: expanded ? "10px" : "20px",
          left: expanded ? "10px" : "20px",
          borderRadius: expanded ? "26px" : "22px",
        }}
        transition={{ type: "spring", stiffness: 240, damping: 30, mass: 0.8 }}
        className="group/bar absolute z-30 flex flex-col overflow-hidden bg-zinc-900 ring-1 ring-white/10"
        style={{ cursor: expanded ? "default" : "pointer" }}
        onClick={() => !expanded && setExpanded(true)}
      >
        <div className={cn("flex h-[68px] shrink-0 items-center justify-between px-3", expanded ? "border-b border-white/[0.06]" : "hover:bg-white/[0.03]")}>
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/[0.06] text-zinc-300 ring-1 ring-inset ring-white/10 transition-transform group-hover/bar:scale-105">
              <Users className="h-5 w-5" />
            </span>
            <div>
              <h4 className="text-[15px] font-medium leading-none text-white">Agent directory</h4>
              <p className="mt-1.5 text-xs leading-none text-zinc-500">
                {agents.length} {agents.length === 1 ? "agent" : "agents"} · {agents.length - liveCount} paused
              </p>
            </div>
          </div>
          {expanded ? (
            <button
              type="button"
              className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/[0.06] text-zinc-400 transition hover:text-white active:scale-90"
              onClick={(e) => {
                e.stopPropagation();
                setExpanded(false);
              }}
              aria-label="Close directory"
            >
              <X className="h-[18px] w-[18px]" />
            </button>
          ) : (
            <div className="flex -space-x-3 pr-1">
              {agents.slice(0, 3).map((a) => (
                <Avatar key={`sum-${a.id}`} agent={a} size="sm" />
              ))}
              {agents.length > 3 && (
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-zinc-800 text-xs text-zinc-300 ring-2 ring-zinc-900">
                  +{agents.length - 3}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <AnimatePresence>
            {expanded && (
              <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} className="px-5 py-4">
                <SearchBox value={dirQuery} onChange={setDirQuery} placeholder="Search all agents…" autoFocus />
              </motion.div>
            )}
          </AnimatePresence>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-5 pb-3">
            <motion.div
              initial="hidden"
              animate={expanded ? "visible" : "hidden"}
              variants={{
                visible: { transition: { staggerChildren: 0.03, delayChildren: 0.1 } },
                hidden: { transition: { staggerChildren: 0.02, staggerDirection: -1 } },
              }}
            >
              {directory.map((a) => (
                <AgentRow key={`dir-${a.id}`} agent={a} onChanged={onChanged} />
              ))}
            </motion.div>
            {expanded && directory.length === 0 && <p className="py-8 text-center text-sm text-zinc-500">No agents match “{dirQuery}”.</p>}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
