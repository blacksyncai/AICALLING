"use client";

import { Copy, X } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { fmtDate, usd, type Entitlements } from "@/components/billing/types";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Field, Input, Select, Spinner } from "@/components/ui";
import { api, fetcher, patch, post } from "@/lib/api";

interface Override {
  id: string;
  key: string;
  value: unknown;
  reason: string;
  expires_at: string | null;
  created_at: string | null;
}

interface AdminOrgPlan {
  entitlements: Omit<Entitlements, "managed_onboarding" | "links"> & { overrides: Override[] };
  managed_onboarding: string | null;
  subscription: {
    id: string; status: string; plan_key: string | null; price_id: string | null; agent_slots: number; phone_quantity: number;
    custom_credits: number | null; cancel_at_period_end: boolean; current_period_end: string | null; updated_at: string | null;
  } | null;
}

const KEYS: { key: string; label: string; kind: "number" | "flag" | "plan" }[] = [
  { key: "agents", label: "Active agents", kind: "number" },
  { key: "seats", label: "Team members", kind: "number" },
  { key: "numbers", label: "Included numbers", kind: "number" },
  { key: "crm", label: "CRM integrations", kind: "number" },
  { key: "concurrency", label: "Calls at once", kind: "number" },
  { key: "workflows", label: "Workflow automations", kind: "flag" },
  { key: "advanced_workflows", label: "Webhooks & API", kind: "flag" },
  { key: "roles", label: "Member roles", kind: "flag" },
  { key: "team_reporting", label: "Team analytics", kind: "flag" },
  { key: "plan", label: "All entitlements of a plan", kind: "plan" },
];

const show = (v: unknown) => (v === null ? "unlimited" : typeof v === "boolean" ? (v ? "on" : "off") : String(v));

/** Admin: an account's plan entitlements, overrides, the Managed payment link, custom quotes and onboarding. */
export function PlanAdminCard({ orgId }: { orgId: string }) {
  const toast = useToast();
  const url = `/api/admin/billing/orgs/${orgId}`;
  const { data, mutate } = useSWR<AdminOrgPlan>(url, fetcher);
  const [busy, setBusy] = useState<string | null>(null);
  const [ov, setOv] = useState({ key: "agents", value: "", reason: "", days: "" });
  const [managed, setManaged] = useState({ amount: "797", credits: "1500", note: "" });
  const [quote, setQuote] = useState({ description: "", amount: "" });
  const [link, setLink] = useState<{ label: string; url: string } | null>(null);

  async function run<T>(key: string, fn: () => Promise<T>, ok?: string) {
    setBusy(key);
    try {
      const r = await fn();
      await mutate();
      if (ok) toast(ok);
      return r;
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  const kind = KEYS.find((k) => k.key === ov.key)?.kind ?? "number";

  async function addOverride() {
    if (ov.reason.trim().length < 3) return toast("Add a reason — it's saved in the audit log.", "error");
    const value = kind === "flag" ? ov.value !== "off" : kind === "plan" ? ov.value || "teams" : ov.value.trim() === "" ? null : Number(ov.value);
    const days = Number(ov.days);
    const expires_at = days > 0 ? new Date(Date.now() + days * 86400_000).toISOString() : null;
    const r = await run("ov", () => post(`${url}/overrides`, { key: ov.key, value, reason: ov.reason.trim(), expires_at }), "Override added");
    if (r) setOv({ ...ov, value: "", reason: "", days: "" });
  }

  async function managedLink() {
    const r = await run("managed", () => post<{ url: string }>(`${url}/managed-checkout`, {
      amount_cents: Math.round(Number(managed.amount) * 100), credits: Number(managed.credits), note: managed.note.trim(),
    }));
    if (r) setLink({ label: "Managed plan payment link", url: r.url });
  }

  async function sendQuote() {
    const r = await run("quote", () => post<{ url: string }>(`${url}/quote`, {
      description: quote.description.trim(), amount_cents: Math.round(Number(quote.amount) * 100),
    }));
    if (r) {
      setLink({ label: "Quote / invoice link", url: r.url });
      setQuote({ description: "", amount: "" });
    }
  }

  if (!data)
    return (
      <Card>
        <CardHeader title="Plan & entitlements" />
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      </Card>
    );

  const e = data.entitlements;
  const s = data.subscription;
  return (
    <Card className="min-w-0">
      <CardHeader
        title="Plan & entitlements"
        description={e.unlimited ? "House account — no limits." : `${e.plan_name ?? "No plan"} · limits from ${e.limits_plan}${e.source === "override" ? " (override)" : ""}`}
      />
      <div className="flex flex-col gap-5 p-5 pt-2 text-sm">
        {s && (
          <div className="rounded-xl bg-zinc-50 p-3 text-xs text-zinc-600 ring-1 ring-zinc-900/5">
            <div className="font-mono">{s.id}</div>
            {s.status} · {s.plan_key ?? "unmanaged price"} · renews {fmtDate(s.current_period_end)}
            {s.cancel_at_period_end && " · ending"} · {s.agent_slots} agent slot{s.agent_slots === 1 ? "" : "s"} · {s.phone_quantity} extra number{s.phone_quantity === 1 ? "" : "s"}
            {s.custom_credits != null && ` · ${s.custom_credits} credits/cycle (custom)`}
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(["agents", "seats", "numbers", "crm"] as const).map((k) => (
            <div key={k} className="rounded-lg bg-white p-2.5 ring-1 ring-zinc-900/[0.06]">
              <div className="text-[11px] text-zinc-500">{k}</div>
              <div className={e.over_limit.includes(k) ? "font-semibold text-red-600" : "font-semibold"}>
                {e.usage[k]} / {e.limits[k] == null ? "∞" : e.limits[k]}
              </div>
            </div>
          ))}
        </div>
        {e.over_limit.length > 0 && <p className="text-xs text-red-600">Over the limit: {e.over_limit.join(", ")} (data is kept; activation is blocked).</p>}

        <div>
          <div className="mb-2 text-xs font-medium text-zinc-700">Overrides</div>
          {e.overrides.length === 0 ? (
            <p className="text-xs text-zinc-500">None.</p>
          ) : (
            <ul className="mb-3 space-y-1.5">
              {e.overrides.map((o) => (
                <li key={o.id} className="flex items-start justify-between gap-2 rounded-lg bg-zinc-50 px-3 py-2 text-xs">
                  <span>
                    <strong>{o.key}</strong> = {show(o.value)} · {o.reason}
                    {o.expires_at && <span className="text-zinc-500"> · until {fmtDate(o.expires_at)}</span>}
                  </span>
                  <button className="text-zinc-400 hover:text-red-600" title="Revoke"
                          onClick={() => void run("rev", () => api(`${url}/overrides/${o.id}`, { method: "DELETE" }), "Override revoked")}>
                    <X className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Entitlement">
              <Select value={ov.key} onChange={(ev) => setOv({ ...ov, key: ev.target.value, value: "" })}>
                {KEYS.map((k) => (
                  <option key={k.key} value={k.key}>{k.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="Value" hint={kind === "number" ? "Empty = unlimited" : undefined}>
              {kind === "flag" ? (
                <Select value={ov.value || "on"} onChange={(ev) => setOv({ ...ov, value: ev.target.value })}>
                  <option value="on">On</option>
                  <option value="off">Off</option>
                </Select>
              ) : kind === "plan" ? (
                <Select value={ov.value || "teams"} onChange={(ev) => setOv({ ...ov, value: ev.target.value })}>
                  {["solo", "growth", "teams", "managed"].map((p) => <option key={p} value={p}>{p}</option>)}
                </Select>
              ) : (
                <Input inputMode="numeric" value={ov.value} onChange={(ev) => setOv({ ...ov, value: ev.target.value.replace(/\D/g, "") })} />
              )}
            </Field>
            <Field label="Reason (audited)">
              <Input value={ov.reason} onChange={(ev) => setOv({ ...ov, reason: ev.target.value })} placeholder="e.g. Pilot, 30-day trial of Teams" />
            </Field>
            <Field label="Days (empty = until revoked)">
              <Input inputMode="numeric" value={ov.days} onChange={(ev) => setOv({ ...ov, days: ev.target.value.replace(/\D/g, "") })} />
            </Field>
          </div>
          <Button className="mt-2" size="sm" loading={busy === "ov"} onClick={() => void addOverride()}>Add override</Button>
        </div>

        <div className="border-t border-zinc-100 pt-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-zinc-700">
            Managed plan
            {data.managed_onboarding && <Badge tone={data.managed_onboarding === "done" ? "green" : "amber"}>onboarding {data.managed_onboarding}</Badge>}
          </div>
          <p className="mb-2 text-xs text-zinc-500">After the discovery call: create a Stripe payment link and send it. Paying it starts Managed and flags the account for onboarding.</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <Field label="$ / month (min 797)">
              <Input inputMode="decimal" value={managed.amount} onChange={(ev) => setManaged({ ...managed, amount: ev.target.value })} />
            </Field>
            <Field label="Credits / month">
              <Input inputMode="numeric" value={managed.credits} onChange={(ev) => setManaged({ ...managed, credits: ev.target.value.replace(/\D/g, "") })} />
            </Field>
            <Field label="Note">
              <Input value={managed.note} onChange={(ev) => setManaged({ ...managed, note: ev.target.value })} />
            </Field>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="primary" loading={busy === "managed"} onClick={() => void managedLink()}>
              Create Managed payment link
            </Button>
            {(["needed", "scheduled", "done"] as const).map((st) => (
              <Button key={st} size="sm" disabled={data.managed_onboarding === st}
                      onClick={() => void run("onb", () => patch(`${url}/onboarding`, { status: st }), `Onboarding: ${st}`)}>
                Mark {st}
              </Button>
            ))}
          </div>
        </div>

        <div className="border-t border-zinc-100 pt-4">
          <div className="mb-2 text-xs font-medium text-zinc-700">Custom quote (developer build, extra Managed work)</div>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Field label="What it's for">
              <Input value={quote.description} onChange={(ev) => setQuote({ ...quote, description: ev.target.value })} placeholder="Custom inbound agent build" />
            </Field>
            <Field label="Amount ($)">
              <Input inputMode="decimal" value={quote.amount} onChange={(ev) => setQuote({ ...quote, amount: ev.target.value })} />
            </Field>
          </div>
          <Button className="mt-2" size="sm" loading={busy === "quote"} disabled={quote.description.trim().length < 3 || !(Number(quote.amount) >= 1)}
                  onClick={() => void sendQuote()}>
            Create invoice link {Number(quote.amount) >= 1 ? `for ${usd(Math.round(Number(quote.amount) * 100))}` : ""}
          </Button>
          <p className="mt-1 text-xs text-zinc-500">Nothing is charged automatically — the customer pays from Stripe&apos;s invoice page (due in 7 days).</p>
        </div>

        {link && (
          <div className="flex items-center gap-2 rounded-xl bg-emerald-50 p-3 text-xs text-emerald-900 ring-1 ring-emerald-100">
            <span className="min-w-0 flex-1 truncate"><strong>{link.label}:</strong> {link.url}</span>
            <button className="shrink-0" title="Copy" onClick={() => { void navigator.clipboard?.writeText(link.url); toast("Link copied"); }}>
              <Copy className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}
