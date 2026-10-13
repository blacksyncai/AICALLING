"use client";

import { Bot, ChevronRight, Crown, Hash, LogIn, Minus, Plus, Wallet } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Badge, Button, Field, Input, Modal } from "@/components/ui";
import { useToast } from "@/components/toast";
import { patch, post } from "@/lib/api";
import { switchOrg } from "@/lib/session";
import type { AdminOrg } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ManagePlanModal } from "./ManagePlan";
import { PhoneNumbersCard } from "./PhoneNumbersCard";
import { fmt } from "./shared";

type Adjust = { org: AdminOrg; kind: "credits" | "lookup"; sign: 1 | -1 };

/** Admin accounts as one card per client: key numbers up top, every common action one click away. */
export function ClientCards({ orgs, onChanged }: { orgs: AdminOrg[]; onChanged: () => void }) {
  const [adjust, setAdjust] = useState<Adjust | null>(null);
  const [numbersFor, setNumbersFor] = useState<AdminOrg | null>(null);
  const [planFor, setPlanFor] = useState<AdminOrg | null>(null);
  return (
    <>
      <div className="flex flex-col gap-4">
        {orgs.map((o) => (
          <ClientCard key={o.id} org={o} onChanged={onChanged} onAdjust={setAdjust} onNumbers={() => setNumbersFor(o)} onPlan={() => setPlanFor(o)} />
        ))}
      </div>
      {planFor && <ManagePlanModal orgId={planFor.id} open onClose={() => setPlanFor(null)} onSaved={onChanged} />}
      <AdjustModal adjust={adjust} onClose={() => setAdjust(null)} onDone={onChanged} />
      <Modal open={!!numbersFor} onClose={() => { setNumbersFor(null); onChanged(); }} title={numbersFor ? `Phone numbers — ${numbersFor.name}` : ""} wide>
        {numbersFor && <PhoneNumbersCard orgId={numbersFor.id} />}
      </Modal>
    </>
  );
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || "?";
}

function talkTime(minutes: number) {
  if (!minutes) return "0m";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function ClientCard({ org: o, onChanged, onAdjust, onNumbers, onPlan }: {
  org: AdminOrg; onChanged: () => void; onAdjust: (a: Adjust) => void; onNumbers: () => void; onPlan: () => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const active = o.status === "active";
  const low = !o.unlimited_credits && o.credits_balance <= 10;

  async function go(path: string) {
    setBusy(path);
    try {
      await switchOrg(o.id, path);
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(null);
    }
  }

  async function toggleActive() {
    const next = active ? "suspended" : "active";
    if (next === "suspended" && !window.confirm(`Suspend ${o.name}? They can still sign in but can't place calls.`)) return;
    setBusy("status");
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

  return (
    <div className="min-w-0 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs sm:p-5">
      <div className="flex flex-wrap items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-zinc-900 text-sm font-semibold text-white">
          {initials(o.name)}
        </span>
        <div className="min-w-0 flex-1">
          <Link href={`/admin/accounts/${o.id}`} className="block truncate text-base font-semibold text-zinc-900 hover:underline">
            {o.name}
          </Link>
          <div className="truncate text-xs text-zinc-500">
            ID {o.id.slice(0, 8)} · {o.owner?.email ?? "No owner"}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onPlan}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-zinc-900 px-2.5 text-xs font-medium text-white hover:bg-zinc-800"
          >
            <Crown className="h-3.5 w-3.5 text-brand-400" /> Manage Plan
          </button>
          <button
            type="button"
            onClick={onNumbers}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
          >
            <Hash className="h-3.5 w-3.5" /> {o.phone_numbers ? `${o.phone_numbers} number${o.phone_numbers === 1 ? "" : "s"}` : "Phone numbers"}
          </button>
          <Badge tone={active ? "green" : "red"}>{active ? "Active" : "Suspended"}</Badge>
          <button
            type="button"
            role="switch"
            aria-checked={active}
            aria-label={active ? `Suspend ${o.name}` : `Activate ${o.name}`}
            disabled={busy === "status"}
            onClick={() => void toggleActive()}
            className={cn("relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50", active ? "bg-emerald-500" : "bg-zinc-300")}
          >
            <span className={cn("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all", active ? "left-[22px]" : "left-0.5")} />
          </button>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Calling credits" value={o.unlimited_credits ? "Unlimited" : fmt(o.credits_balance)} tone={low ? "amber" : undefined} />
        <Stat label="Talk time" value={talkTime(o.all_time?.minutes ?? 0)} sub={`${fmt(o.usage_30d.calls)} calls · 30d`} />
        <Stat label="Agents" value={fmt(o.agents)} sub={`${fmt(o.members)} team · ${fmt(o.contacts)} contacts`} />
        <Stat
          label="Lookup balance"
          value={o.lead_credits_unlimited ? "Unlimited" : `$${((o.lookup_balance_cents ?? 0) / 100).toFixed(2)}`}
          sub={o.lead_credits ? `${fmt(o.lead_credits)} prepaid lookups` : undefined}
        />
      </dl>

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Action onClick={() => void go("/dashboard")} loading={busy === "/dashboard"} icon={<LogIn className="h-4 w-4" />} tone="blue">
          Access account
        </Action>
        <Action onClick={() => void go("/agents")} loading={busy === "/agents"} icon={<Bot className="h-4 w-4" />} tone="blue">
          Manage agents
        </Action>
        <Action onClick={() => onAdjust({ org: o, kind: "credits", sign: 1 })} icon={<Plus className="h-4 w-4" />} tone="violet" disabled={o.unlimited_credits}>
          Add credits
        </Action>
        <Action onClick={() => onAdjust({ org: o, kind: "credits", sign: -1 })} icon={<Minus className="h-4 w-4" />} tone="red" disabled={o.unlimited_credits || o.credits_balance <= 0}>
          Remove credits
        </Action>
        <Action onClick={() => onAdjust({ org: o, kind: "lookup", sign: 1 })} icon={<Wallet className="h-4 w-4" />} tone="amber">
          Lookup funds
        </Action>
        <Link
          href={`/admin/accounts/${o.id}`}
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg border border-zinc-200 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
        >
          Details <ChevronRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "amber" }) {
  return (
    <div className="min-w-0 rounded-lg bg-zinc-50 px-3 py-2.5">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className={cn("truncate font-display text-lg font-semibold tabular-nums", tone === "amber" ? "text-amber-700" : "text-zinc-900")}>{value}</dd>
      {sub && <dd className="truncate text-[11px] text-zinc-400">{sub}</dd>}
    </div>
  );
}

const ACTION_TONE = {
  blue: "bg-sky-50 text-sky-800 hover:bg-sky-100",
  violet: "bg-violet-50 text-violet-800 hover:bg-violet-100",
  red: "bg-red-50 text-red-700 hover:bg-red-100",
  amber: "bg-amber-50 text-amber-800 hover:bg-amber-100",
} as const;

function Action({ onClick, icon, tone, children, loading, disabled }: {
  onClick: () => void; icon: React.ReactNode; tone: keyof typeof ACTION_TONE; children: React.ReactNode; loading?: boolean; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading || disabled}
      className={cn("inline-flex h-10 items-center justify-center gap-1.5 rounded-lg px-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40", ACTION_TONE[tone])}
    >
      {icon}
      <span className="truncate">{loading ? "Opening…" : children}</span>
    </button>
  );
}

const PRESETS = { credits: [60, 300, 1000], lookup: [5, 10, 25] } as const;

function AdjustModal({ adjust, onClose, onDone }: { adjust: Adjust | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const close = () => {
    setAmount("");
    setReason("");
    onClose();
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!adjust) return;
    const n = Number(amount);
    if (!(n > 0)) return toast("Enter an amount.", "error");
    if (reason.trim().length < 3) return toast("Add a short reason — it's saved in the audit log.", "error");
    setBusy(true);
    try {
      if (adjust.kind === "credits") {
        const r = await post<{ balance: number }>(`/api/admin/orgs/${adjust.org.id}/credits`, {
          amount: adjust.sign * Math.round(n), note: reason.trim(),
        });
        toast(`${adjust.org.name}: ${fmt(r.balance)} calling credits`);
      } else {
        const r = await post<{ balance_cents: number }>(`/api/admin/orgs/${adjust.org.id}/lookup-balance`, {
          amount_cents: adjust.sign * Math.round(n * 100), reason: reason.trim(),
        });
        toast(`${adjust.org.name}: $${(r.balance_cents / 100).toFixed(2)} lookup balance`);
      }
      onDone();
      close();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const kind = adjust?.kind ?? "credits";
  const title = !adjust ? "" : `${adjust.sign > 0 ? "Add" : "Remove"} ${kind === "credits" ? "calling credits" : "lookup funds"} — ${adjust.org.name}`;
  return (
    <Modal open={!!adjust} onClose={close} title={title}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        {adjust && (
          <p className="text-sm text-zinc-600">
            Current:{" "}
            <strong>
              {kind === "credits" ? `${fmt(adjust.org.credits_balance)} credits` : `$${((adjust.org.lookup_balance_cents ?? 0) / 100).toFixed(2)}`}
            </strong>
            {adjust.sign < 0 && " — balances never go below zero."}
          </p>
        )}
        <Field label={kind === "credits" ? "Credits" : "Amount ($)"}>
          <Input autoFocus inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} placeholder="0" />
        </Field>
        <div className="flex flex-wrap gap-2">
          {PRESETS[kind].map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setAmount(String(p))}
              className="rounded-full border border-zinc-200 px-3 py-1 text-xs font-medium text-zinc-700 hover:border-brand-300 hover:bg-brand-50"
            >
              {kind === "credits" ? fmt(p) : `$${p}`}
            </button>
          ))}
        </div>
        <Field label="Reason (saved in the audit log)">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Monthly top-up, goodwill, correction" />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" variant={adjust?.sign === -1 ? "secondary" : "primary"} loading={busy}>
            {adjust?.sign === -1 ? "Remove" : "Add"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
