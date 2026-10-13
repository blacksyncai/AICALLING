"use client";

import { Crown, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fmtDate, fmtDateTime, usd } from "@/components/billing/types";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Field, Input, Modal, Spinner, Textarea } from "@/components/ui";
import { fetcher, put } from "@/lib/api";
import { cn } from "@/lib/utils";

type Mode = "billing" | "manual" | "complimentary";

export interface PlanView {
  org: { id: string; name: string; owner: { name: string; email: string } | null };
  billing: { plan: string | null; name: string | null; status: string; live: boolean; amount_cents: number | null };
  subscription_id: string | null;
  current_period_end: string | null;
  effective: { plan: string; name: string | null; source: string; unlimited: boolean };
  controlled_by: "stripe" | "admin_override" | "no_plan";
  override: { id: string; mode: Mode; plan: string; reason: string; expires_at: string | null; assigned_at: string | null } | null;
  assigned_at: string | null;
  credits_balance: number | null;
  plans: { key: string; name: string; amount_cents: number }[];
  history: { previous: string; change: string; new: string; reason: string; admin_id: string | null; at: string | null }[];
}

const CONTROL: Record<PlanView["controlled_by"], string> = {
  stripe: "Stripe subscription", admin_override: "Admin override", no_plan: "No plan (trial defaults)",
};
const MODES: { value: Mode; title: string; text: string }[] = [
  { value: "billing", title: "Standard billing", text: "Access follows the paid subscription." },
  { value: "manual", title: "Manual plan override", text: "A different tier than the one they pay for." },
  { value: "complimentary", title: "Complimentary access", text: "Plan access without a subscription." },
];
const CHANGE: Record<string, string> = { manual_override: "Manual override", complimentary: "Complimentary", removed: "Returned to billing", expired: "Expired" };

function Summary({ v }: { v: PlanView }) {
  const rows: [string, React.ReactNode][] = [
    ["Organization", v.org.name],
    ["Account owner", v.org.owner ? `${v.org.owner.name || v.org.owner.email} · ${v.org.owner.email}` : "—"],
    ["Subscription plan", v.billing.live && v.billing.name ? `${v.billing.name}${v.billing.amount_cents != null ? ` — ${usd(v.billing.amount_cents, 0)}/mo` : " (custom price)"}` : "None"],
    ["Billing status", v.billing.status === "none" ? "No subscription" : v.billing.status],
    ["Effective access", v.effective.unlimited ? "Unlimited (house account)" : v.effective.name ?? v.effective.plan],
    ["Controlled by", CONTROL[v.controlled_by]],
    ["Calling credits", v.credits_balance == null ? "Unlimited" : v.credits_balance.toLocaleString()],
    ["Plan assigned", fmtDate(v.assigned_at)],
  ];
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2.5 text-sm sm:grid-cols-2">
      {rows.map(([k, val]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-zinc-500">{k}</dt>
          <dd className="truncate font-medium text-zinc-900">{val}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Admin: assign an access plan. Never charges, never touches the Stripe subscription or credits. */
export function ManagePlanModal({ orgId, open, onClose, onSaved }: { orgId: string; open: boolean; onClose: () => void; onSaved?: () => void }) {
  const toast = useToast();
  const url = `/api/admin/billing/orgs/${orgId}/plan`;
  const { data, mutate } = useSWR<PlanView>(open ? url : null, fetcher);
  const [mode, setMode] = useState<Mode>("billing");
  const [plan, setPlan] = useState("growth");
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  useEffect(() => {
    // Fill the form once per opening — a background refresh mustn't undo the admin's choices.
    if (!data || loadedFor === data.org.id) return;
    setLoadedFor(data.org.id);
    setMode(data.override?.mode ?? "billing");
    setPlan(data.override?.plan ?? (data.billing.plan && data.billing.plan !== "managed" ? "growth" : "teams"));
    setUntil(data.override?.expires_at ? data.override.expires_at.slice(0, 10) : "");
    setReason("");
  }, [data, loadedFor]);

  useEffect(() => {
    if (!open) setLoadedFor(null);
  }, [open]);

  async function apply() {
    setSaving(true);
    try {
      await put(url, {
        mode, plan: mode === "billing" ? null : plan, reason: reason.trim(),
        expires_at: mode !== "billing" && until ? new Date(`${until}T23:59:59`).toISOString() : null,
      });
      await mutate();
      onSaved?.();
      toast(mode === "billing" ? "Access now follows billing" : `Access set to ${data?.plans.find((p) => p.key === plan)?.name}`);
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Manage plan" wide>
      {!data ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <div className="space-y-6 text-zinc-900">
          <div className="rounded-2xl bg-zinc-50 p-4 ring-1 ring-zinc-900/5"><Summary v={data} /></div>

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Access</div>
            <div className="grid gap-2 sm:grid-cols-3">
              {MODES.map((m) => (
                <button key={m.value} type="button" onClick={() => setMode(m.value)}
                  className={cn("rounded-2xl p-3.5 text-left ring-1 transition",
                    mode === m.value ? "bg-zinc-950 text-white ring-zinc-950" : "bg-white ring-zinc-900/10 hover:bg-zinc-50")}>
                  <div className="text-sm font-semibold">{m.title}</div>
                  <div className={cn("mt-0.5 text-xs", mode === m.value ? "text-zinc-400" : "text-zinc-500")}>{m.text}</div>
                </button>
              ))}
            </div>
          </div>

          {mode !== "billing" && (
            <div className="space-y-4">
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Plan</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {data.plans.map((p) => (
                    <button key={p.key} type="button" onClick={() => setPlan(p.key)}
                      className={cn("rounded-xl px-3 py-2.5 text-left ring-1 transition",
                        plan === p.key ? "bg-brand-50 ring-2 ring-brand-500" : "bg-white ring-zinc-900/10 hover:bg-zinc-50")}>
                      <div className="text-sm font-semibold">{p.name}</div>
                      <div className="text-[11px] text-zinc-500">list {usd(p.amount_cents, 0)}/mo</div>
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Ends on (optional)" hint="Leave empty to keep it until you remove it.">
                  <Input type="date" value={until} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setUntil(e.target.value)} />
                </Field>
                <Field label="Internal note (optional)" hint="Only BlackSync admins see this.">
                  <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Referral thank-you, pilot through Q1" />
                </Field>
              </div>
            </div>
          )}
          {mode === "billing" && data.override && (
            <Field label="Internal note (optional)">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why the override is being removed" />
            </Field>
          )}

          <p className="flex items-start gap-2 rounded-xl bg-emerald-50 px-3.5 py-2.5 text-xs text-emerald-900 ring-1 ring-emerald-100">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            Applying a plan changes feature access only. It doesn&apos;t charge the customer, change their Stripe subscription or invoices, or add or remove calling credits.
          </p>

          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" loading={saving} onClick={() => void apply()}
              disabled={mode === "billing" && !data.override}>
              {mode === "billing" ? "Return to billing plan" : "Apply Plan"}
            </Button>
          </div>

          {data.history.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">History</div>
              <ul className="space-y-1.5 text-xs">
                {data.history.map((h, i) => (
                  <li key={i} className="rounded-lg bg-zinc-50 px-3 py-2">
                    <span className="font-medium text-zinc-900">{CHANGE[h.change] ?? h.change}</span>: {h.previous} → {h.new}
                    <span className="text-zinc-500"> · {fmtDateTime(h.at)}{h.admin_id ? "" : " · automatic"}</span>
                    {h.reason && <div className="text-zinc-500">{h.reason}</div>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

/** Admin account page: plan at a glance + Manage Plan. */
export function ManagePlanCard({ orgId }: { orgId: string }) {
  const { data, mutate } = useSWR<PlanView>(`/api/admin/billing/orgs/${orgId}/plan`, fetcher);
  const [open, setOpen] = useState(false);
  return (
    <Card className="min-w-0">
      <CardHeader
        title="Plan & access"
        action={<Button size="sm" variant="primary" onClick={() => setOpen(true)}><Crown className="h-3.5 w-3.5" /> Manage Plan</Button>}
      />
      <div className="p-5 pt-2">
        {!data ? (
          <div className="flex justify-center py-6"><Spinner /></div>
        ) : (
          <>
            {data.controlled_by === "admin_override" && data.override && (
              <div className="mb-3">
                <Badge tone="amber">
                  {data.override.mode === "complimentary" ? "Complimentary" : "Manual override"}
                  {data.override.expires_at ? ` · until ${fmtDate(data.override.expires_at)}` : " · no end date"}
                </Badge>
              </div>
            )}
            <Summary v={data} />
          </>
        )}
      </div>
      <ManagePlanModal orgId={orgId} open={open} onClose={() => setOpen(false)} onSaved={() => void mutate()} />
    </Card>
  );
}
