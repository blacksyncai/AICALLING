"use client";

import { ArrowDown, ArrowUp, Bot, ChevronRight, Crown, Hash, LogIn, Minus, MoreHorizontal, Plus, Wallet } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Modal } from "@/components/ui";
import { useToast } from "@/components/toast";
import { patch } from "@/lib/api";
import { switchOrg } from "@/lib/session";
import type { AdminOrg } from "@/lib/types";
import { cn, parseDate, timeAgo } from "@/lib/utils";
import { AdjustModal, type Adjust } from "./ClientCards";
import { ManagePlanModal } from "./ManagePlan";
import { PhoneNumbersCard } from "./PhoneNumbersCard";
import { fmt } from "./shared";

/* Every client in one dense, sortable table: filter to what needs attention, act from the row. */

const LOW = 10;
const DAY = 86_400_000;

type SortKey = "name" | "plan" | "credits" | "calls" | "talk" | "last" | "created";
type Filter = "all" | "attention" | "low" | "suspended" | "active" | "quiet" | "no_plan";

const isLow = (o: AdminOrg) => !o.unlimited_credits && o.credits_balance <= LOW;
const lastMs = (o: AdminOrg) => parseDate(o.last_call_at)?.getTime() ?? 0;
const FILTERS: { key: Filter; label: string; test: (o: AdminOrg) => boolean; tone?: string }[] = [
  { key: "all", label: "All", test: () => true },
  { key: "attention", label: "Needs attention", test: (o) => isLow(o) || o.status !== "active" || o.plan_status === "past_due", tone: "text-red-600" },
  { key: "low", label: "Low credits", test: isLow, tone: "text-amber-600" },
  { key: "suspended", label: "Suspended", test: (o) => o.status !== "active" },
  { key: "active", label: "Called this week", test: (o) => Date.now() - lastMs(o) < 7 * DAY },
  { key: "quiet", label: "Quiet 30d+", test: (o) => Date.now() - lastMs(o) > 30 * DAY },
  { key: "no_plan", label: "No plan", test: (o) => !o.plan },
];

const SORTS: Record<SortKey, (o: AdminOrg) => number | string> = {
  name: (o) => o.name.toLowerCase(),
  plan: (o) => o.plan ?? "",
  credits: (o) => (o.unlimited_credits ? Infinity : o.credits_balance),
  calls: (o) => o.usage_30d.calls,
  talk: (o) => o.usage_30d.minutes,
  last: lastMs,
  created: (o) => parseDate(o.created_at)?.getTime() ?? 0,
};

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || "?";
}
const talk = (m: number) => (!m ? "0m" : m >= 60 ? `${Math.floor(m / 60)}h ${Math.round(m % 60)}m` : `${Math.round(m)}m`);

export function ClientsTable({ orgs, onChanged }: { orgs: AdminOrg[]; onChanged: () => void }) {
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "last", dir: -1 });
  const [adjust, setAdjust] = useState<Adjust | null>(null);
  const [numbersFor, setNumbersFor] = useState<AdminOrg | null>(null);
  const [planFor, setPlanFor] = useState<AdminOrg | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.key, orgs.filter(f.test).length])) as Record<Filter, number>, [orgs]);
  const rows = useMemo(() => {
    const test = FILTERS.find((f) => f.key === filter)!.test;
    const get = SORTS[sort.key];
    return orgs.filter(test).sort((a, b) => {
      const x = get(a), y = get(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [orgs, filter, sort]);

  async function open(o: AdminOrg, path = "/dashboard") {
    setBusy(o.id + path);
    try {
      await switchOrg(o.id, path);
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(null);
    }
  }

  async function toggle(o: AdminOrg) {
    const next = o.status === "active" ? "suspended" : "active";
    if (next === "suspended" && !window.confirm(`Suspend ${o.name}? They can still sign in but can't place calls.`)) return;
    setBusy(o.id + "status");
    try {
      await patch(`/api/admin/orgs/${o.id}`, { status: next });
      onChanged();
      toast(next === "active" ? `${o.name} is active` : `${o.name} is suspended`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  const head = (key: SortKey, label: string, cls = "") => (
    <th className={cn("px-3 py-3", cls)}>
      <button
        type="button"
        onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "name" || key === "plan" ? 1 : -1 }))}
        className={cn("inline-flex items-center gap-1 uppercase tracking-wider hover:text-zinc-700", sort.key === key && "text-zinc-800")}
      >
        {label}
        {sort.key === key && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  );

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-zinc-200/80 bg-white shadow-xs">
      <div className="-mx-1 flex gap-1.5 overflow-x-auto border-b border-zinc-100 px-5 py-3">
        {FILTERS.map((f) => {
          const on = filter === f.key;
          const n = counts[f.key];
          if (f.key !== "all" && f.key !== filter && n === 0) return null;
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                on ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200/70",
              )}
            >
              {f.label}
              <span className={cn("rounded-full px-1.5 tabular-nums", on ? "bg-white/15" : cn("bg-white", f.tone ?? "text-zinc-500"))}>{n}</span>
            </button>
          );
        })}
      </div>

      {rows.length === 0 ? (
        <p className="px-5 py-12 text-center text-sm text-zinc-500">Nothing here — every client is fine on this one.</p>
      ) : (
        <>
          {/* Phones: compact cards */}
          <ul className="divide-y divide-zinc-100 md:hidden">
            {rows.map((o) => (
              <li key={o.id} className="flex items-center gap-3 px-4 py-3">
                <Link href={`/admin/accounts/${o.id}`} className="flex min-w-0 flex-1 items-center gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-900 text-xs font-semibold text-white">{initials(o.name)}</span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate font-semibold text-zinc-900">{o.name}</span>
                      {o.status !== "active" && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" title="Suspended" />}
                    </span>
                    <span className="block truncate text-xs text-zinc-500">
                      <span className={cn(isLow(o) && "font-medium text-amber-600")}>{o.unlimited_credits ? "∞" : fmt(o.credits_balance)} cr</span> · {fmt(o.usage_30d.calls)} calls · {o.last_call_at ? timeAgo(o.last_call_at) : "never called"}
                    </span>
                  </span>
                </Link>
                <button onClick={() => void open(o)} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full bg-zinc-900 px-3 text-xs font-medium text-white">
                  <LogIn className="h-3.5 w-3.5" /> Open
                </button>
              </li>
            ))}
          </ul>

          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[1040px] text-sm">
              <thead className="text-left text-[11px] font-semibold text-zinc-400">
                <tr className="border-b border-zinc-100">
                  <th className="px-5 py-3">
                    <button type="button" onClick={() => setSort((s) => ({ key: "name", dir: s.key === "name" ? (s.dir === 1 ? -1 : 1) : 1 }))} className={cn("inline-flex items-center gap-1 uppercase tracking-wider hover:text-zinc-700", sort.key === "name" && "text-zinc-800")}>
                      Client {sort.key === "name" && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                    </button>
                  </th>
                  {head("plan", "Plan")}
                  {head("credits", "Credits", "text-right")}
                  {head("calls", "Calls 30d", "text-right")}
                  {head("talk", "Talk 30d", "text-right")}
                  <th className="px-3 py-3 text-right uppercase tracking-wider">Agents · #s</th>
                  {head("last", "Last call")}
                  <th className="px-3 py-3 uppercase tracking-wider">Active</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100/80">
                {rows.map((o) => {
                  const last = lastMs(o);
                  const stale = !last || Date.now() - last > 14 * DAY;
                  return (
                    <tr key={o.id} className={cn("group transition-colors hover:bg-zinc-50/80", o.status !== "active" && "bg-red-50/30")}>
                      <td className="max-w-[280px] px-5 py-2.5">
                        <Link href={`/admin/accounts/${o.id}`} className="flex min-w-0 items-center gap-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-900 text-xs font-semibold text-white">{initials(o.name)}</span>
                          <span className="min-w-0">
                            <span className="block truncate font-semibold text-zinc-900 group-hover:underline">{o.name}</span>
                            <span className="block truncate text-xs text-zinc-400">{o.owner?.email ?? "No owner"}</span>
                          </span>
                        </Link>
                      </td>
                      <td className="px-3 py-2.5">
                        <button type="button" onClick={() => setPlanFor(o)} title="Manage plan" className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset", o.plan ? (o.plan_status === "past_due" ? "bg-red-50 text-red-700 ring-red-600/10" : "bg-violet-50 text-violet-700 ring-violet-600/10") : "bg-zinc-50 text-zinc-500 ring-zinc-500/10 hover:bg-zinc-100")}>
                          {o.plan ? <Crown className="h-3 w-3" /> : null}
                          {o.plan ? `${o.plan}${o.plan_status === "past_due" ? " · past due" : ""}` : "No plan"}
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right">
                        <span className="inline-flex items-center gap-1.5">
                          <span className={cn("font-medium tabular-nums", isLow(o) ? "text-amber-600" : "text-zinc-900")}>{o.unlimited_credits ? "Unlimited" : fmt(o.credits_balance)}</span>
                          {!o.unlimited_credits && (
                            <button type="button" onClick={() => setAdjust({ org: o, kind: "credits", sign: 1 })} title="Add credits" aria-label={`Add credits to ${o.name}`} className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-100 text-zinc-600 opacity-60 transition hover:bg-zinc-900 hover:text-white group-hover:opacity-100">
                              <Plus className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-zinc-700">{fmt(o.usage_30d.calls)}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-zinc-700">{talk(o.usage_30d.minutes)}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right text-xs tabular-nums text-zinc-500">
                        {fmt(o.agents)} ·{" "}
                        <button type="button" onClick={() => setNumbersFor(o)} className="underline-offset-2 hover:text-zinc-900 hover:underline">
                          {fmt(o.phone_numbers ?? 0)}
                        </button>
                      </td>
                      <td className={cn("whitespace-nowrap px-3 py-2.5 text-xs", stale ? "text-red-500" : "text-zinc-500")}>{o.last_call_at ? timeAgo(o.last_call_at) : "Never"}</td>
                      <td className="px-3 py-2.5">
                        <button
                          type="button"
                          role="switch"
                          aria-checked={o.status === "active"}
                          aria-label={o.status === "active" ? `Suspend ${o.name}` : `Activate ${o.name}`}
                          disabled={busy === o.id + "status"}
                          onClick={() => void toggle(o)}
                          className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50", o.status === "active" ? "bg-emerald-500" : "bg-zinc-300")}
                        >
                          <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", o.status === "active" ? "left-[18px]" : "left-0.5")} />
                        </button>
                      </td>
                      <td className="px-5 py-2.5">
                        <div className="flex items-center justify-end gap-1">
                          <button type="button" onClick={() => void open(o)} disabled={busy === o.id + "/dashboard"} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-zinc-900 px-3 text-xs font-medium text-white transition hover:bg-zinc-700 disabled:opacity-60">
                            <LogIn className="h-3.5 w-3.5" /> {busy === o.id + "/dashboard" ? "Opening…" : "Open"}
                          </button>
                          <RowMenu
                            open={menu === o.id}
                            onToggle={() => setMenu((m) => (m === o.id ? null : o.id))}
                            onClose={() => setMenu(null)}
                            items={[
                              { label: "Manage agents", icon: Bot, onClick: () => void open(o, "/agents") },
                              { label: "Manage plan", icon: Crown, onClick: () => setPlanFor(o) },
                              { label: "Phone numbers", icon: Hash, onClick: () => setNumbersFor(o) },
                              { label: "Add credits", icon: Plus, onClick: () => setAdjust({ org: o, kind: "credits", sign: 1 }), disabled: o.unlimited_credits },
                              { label: "Remove credits", icon: Minus, onClick: () => setAdjust({ org: o, kind: "credits", sign: -1 }), disabled: o.unlimited_credits || o.credits_balance <= 0 },
                              { label: "Lookup funds", icon: Wallet, onClick: () => setAdjust({ org: o, kind: "lookup", sign: 1 }) },
                              { label: "Account details", icon: ChevronRight, href: `/admin/accounts/${o.id}` },
                            ]}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {planFor && <ManagePlanModal orgId={planFor.id} open onClose={() => setPlanFor(null)} onSaved={onChanged} />}
      <AdjustModal adjust={adjust} onClose={() => setAdjust(null)} onDone={onChanged} />
      <Modal open={!!numbersFor} onClose={() => { setNumbersFor(null); onChanged(); }} title={numbersFor ? `Phone numbers — ${numbersFor.name}` : ""} wide>
        {numbersFor && <PhoneNumbersCard orgId={numbersFor.id} />}
      </Modal>
    </div>
  );
}

type MenuItem = { label: string; icon: typeof Bot; onClick?: () => void; href?: string; disabled?: boolean };

function RowMenu({ open, onToggle, onClose, items }: { open: boolean; onToggle: () => void; onClose: () => void; items: MenuItem[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open, onClose]);
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={onToggle} aria-label="More actions" aria-expanded={open} className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900">
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-30 w-48 overflow-hidden rounded-xl border border-zinc-200 bg-white py-1 shadow-xl">
          {items.map((it) => {
            const body = (
              <>
                <it.icon className="h-3.5 w-3.5 text-zinc-400" />
                {it.label}
              </>
            );
            const cls = "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-zinc-700 hover:bg-zinc-50 disabled:pointer-events-none disabled:opacity-40";
            return it.href ? (
              <Link key={it.label} href={it.href} className={cls} onClick={onClose}>
                {body}
              </Link>
            ) : (
              <button key={it.label} type="button" disabled={it.disabled} className={cls} onClick={() => { onClose(); it.onClick?.(); }}>
                {body}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
