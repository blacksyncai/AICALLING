"use client";

import { CalendarCheck, ExternalLink, Minus, Plus } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Modal, Notice, Spinner } from "@/components/ui";
import { PricingHeading } from "@/components/ui/pricing";
import { fetcher, post } from "@/lib/api";
import { CountryPopup } from "./CountryPopup";
import { type CheckoutResult, startCheckout } from "@/lib/helcim";
import { cn } from "@/lib/utils";
import { PlanCards, type PlanAction } from "./PlanCards";
import { Card, CardHeader } from "./surface";
import { type Catalog, type Entitlements, type Plan, fmtDate, usd } from "./types";

interface Preview {
  plan: string;
  upgrade: boolean;
  amount_due_now_cents: number;
  next_invoice_total_cents: number | null;
  next_period_end: string | null;
  new_monthly_cents: number;
  included_credits_now: number;
  downgrade_effects?: string[];
}

interface SlotPreview {
  current: number;
  quantity: number;
  unit_cents: number;
  monthly_change_cents: number;
  new_monthly_addon_cents: number;
  agent_limit: number | null;
  active_agents: number;
  over_after: boolean;
  proration: string;
}

const LIMIT_LABELS: Record<string, string> = { agents: "Active agents", seats: "Team members", numbers: "Phone numbers", crm: "CRMs connected" };

function Usage({ ent }: { ent: Entitlements }) {
  const keys = ["agents", "seats", "numbers", "crm"] as const;
  return (
    <div className="grid gap-3 px-6 pb-5 sm:grid-cols-4">
      {keys.map((k) => {
        const limit = ent.limits[k];
        const used = ent.usage[k];
        const over = ent.over_limit.includes(k);
        const pct = limit == null ? 0 : limit === 0 ? 100 : Math.min(100, (used / limit) * 100);
        return (
          <div key={k} className="rounded-xl bg-zinc-50 p-3 ring-1 ring-zinc-900/5">
            <div className="text-xs text-zinc-500">{LIMIT_LABELS[k]}</div>
            {limit === 0 && used === 0 ? (
              <div className="mt-0.5 text-sm font-medium text-zinc-400">Not on this plan</div>
            ) : (
              <div className={cn("mt-0.5 text-lg font-semibold tabular-nums", over ? "text-red-600" : "text-zinc-900")}>
                {used}
                <span className="text-sm font-normal text-zinc-400"> / {limit == null ? "∞" : limit}{k === "numbers" ? " incl." : ""}</span>
              </div>
            )}
            {limit != null && limit > 0 && (
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-200">
                <div className={cn("h-full rounded-full", over ? "bg-red-500" : pct >= 100 ? "bg-amber-500" : "bg-brand-500")} style={{ width: `${pct}%` }} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function PlansTab({ canManage, refresh }: { canManage: boolean; refresh: () => void }) {
  const toast = useToast();
  const { data, mutate } = useSWR<Catalog>("/api/billing/catalog", fetcher);
  const { data: ent, mutate: mutateEnt } = useSWR<Entitlements>("/api/billing/entitlements", fetcher);
  const [busy, setBusy] = useState<string | null>(null);
  const { data: countryData } = useSWR<{ country: string }>("/api/billing/country", fetcher);
  const [askCountry, setAskCountry] = useState<Plan | null>(null); // plan waiting on the pop-up
  const [preview, setPreview] = useState<{ plan: Plan; data: Preview } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [slots, setSlots] = useState<SlotPreview | null>(null);
  const focus = useSearchParams().get("plan");

  useEffect(() => {
    if (!data) return;
    const id = focus ? `plan-${focus}` : typeof window !== "undefined" ? window.location.hash.slice(1) : "";
    if (id) document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [data, focus]);

  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  const current = data.current_plan;
  const live = ["active", "trialing", "past_due"].includes(current.status);

  const managedNow = live && (current.plan_key === "managed" || !!current.custom);

  function action(p: Plan): PlanAction {
    if (live && current.plan_key === p.key) return { label: "Current plan", disabled: true, muted: true };
    if (!p.self_serve) return { label: "Contact Sales", href: data!.links.sales_booking_url };
    if (!p.available) return { label: "Not available yet", disabled: true };
    return {
      label: live ? `Switch to ${p.name}` : `Get ${p.name}`,
      onClick: () => void choose(p),
      loading: busy === p.key,
      disabled: !canManage || !!busy || (live && current.managed === false) || managedNow,
    };
  }

  async function previewSlots(quantity: number) {
    if (quantity < 0) return;
    setBusy("slots");
    try {
      setSlots(await post<SlotPreview>("/api/billing/addons/agents/preview", { quantity }));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function applySlots() {
    if (!slots) return;
    setConfirming(true);
    try {
      await post("/api/billing/addons/agents", { quantity: slots.quantity, confirm: true });
      setSlots(null);
      await Promise.all([mutate(), mutateEnt()]);
      refresh();
      toast(`You now have ${slots.quantity} extra agent slot${slots.quantity === 1 ? "" : "s"}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setConfirming(false);
    }
  }

  async function choose(plan: Plan, planCountry?: string) {
    setBusy(plan.key);
    try {
      if (!live) {
        if (!planCountry) {
          setAskCountry(plan);
          setBusy(null);
          return;
        }
        const res = await startCheckout(await post<CheckoutResult>(`/api/billing/plans/${plan.key}/checkout`));
        if (res === "redirect") return; // stays busy while the browser leaves for checkout
        if (res) {
          await Promise.all([mutate(), mutateEnt()]);
          refresh();
          toast(`You're now on ${plan.name}`);
        }
        setBusy(null);
        return;
      }
      setPreview({ plan, data: await post<Preview>(`/api/billing/plans/${plan.key}/preview`) });
      setBusy(null);
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(null);
    }
  }

  async function confirmChange() {
    if (!preview) return;
    setConfirming(true);
    try {
      await post(`/api/billing/plans/${preview.plan.key}/change`, { confirm: true });
      setPreview(null);
      await Promise.all([mutate(), mutateEnt()]);
      refresh();
      toast(`You're now on ${preview.plan.name}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setConfirming(false);
    }
  }

  async function cancel(resume: boolean) {
    if (!resume && !window.confirm(`Cancel ${current.name}? It stays active until ${fmtDate(current.current_period_end)}, then stops renewing. Purchased credits are kept.`)) return;
    setBusy("cancel");
    try {
      await post(`/api/billing/subscription/${resume ? "resume" : "cancel"}`);
      await mutate();
      refresh();
      toast(resume ? "Your plan will keep renewing" : "Your plan will end at the close of this billing period");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function portal() {
    setBusy("portal");
    try {
      window.location.href = (await post<{ url: string }>("/api/billing/portal")).url;
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {live && current.managed === false && (
        <Notice tone="blue">
          You&apos;re on <strong>{current.name}</strong>, a plan set up specially for your account. It stays as it is — contact us to make changes.
        </Notice>
      )}
      {ent?.managed_onboarding === "needed" && (
        <Card className="flex flex-wrap items-center justify-between gap-3 rounded-2xl p-5">
          <div className="text-sm text-zinc-700">
            <strong>Welcome to Managed.</strong> Book your onboarding call and our team will build and set up your agents, campaigns and CRM.
          </div>
          <a href={ent.links.onboarding_booking_url} target="_blank" rel="noreferrer"
             className="inline-flex h-10 items-center gap-2 rounded-full bg-gradient-to-t from-brand-600 to-brand-500 px-5 text-sm font-semibold text-white shadow-sm shadow-brand-500/30">
            <CalendarCheck className="h-4 w-4" /> Book an Onboarding Call
          </a>
        </Card>
      )}
      {ent?.source === "override" && (
        <Card className="flex flex-wrap items-center gap-x-8 gap-y-2 rounded-2xl p-5 text-sm">
          <div>
            <div className="text-xs text-zinc-500">Current access</div>
            <div className="text-base font-semibold text-zinc-900">
              {ent.plan_name}
              {ent.override?.expires_at && <span className="ml-2 text-xs font-normal text-zinc-500">until {fmtDate(ent.override.expires_at)}</span>}
            </div>
          </div>
          <div>
            <div className="text-xs text-zinc-500">Billing</div>
            <div className="text-base font-semibold text-zinc-900">
              {ent.billing.live && ent.billing.name
                ? <>{ent.billing.name}{ent.billing.amount_cents != null && <span className="font-normal text-zinc-600"> — {usd(ent.billing.amount_cents, 0)}/month</span>}</>
                : "No paid plan"}
            </div>
          </div>
          <p className="basis-full text-xs text-zinc-500 sm:basis-auto sm:flex-1">
            BlackSync set up {ent.plan_name} access for your account. You&apos;re only billed for what&apos;s shown under Billing.
          </p>
        </Card>
      )}
      <PricingHeading title="A plan that fits your team" description="Every plan includes calling credits each month. Buy more any time — they never expire." />
      <PlanCards plans={data.plans} currentKey={live ? current.plan_key : null} action={action} focus={focus} />
      <p className="text-xs text-zinc-500">
        Included credits are added each time a billing period is paid and expire at the end of it. Credits you buy separately never expire.
        Plan upgrades and add-ons are prorated: the difference for the rest of the period is charged now; when you lower a plan or add-on, unused time is credited to your next invoice.
        Managed is set up with our team after a short call — work beyond its scope is quoted separately. Prices in USD; taxes may apply.
      </p>

      {ent && !ent.unlimited && (
        <Card>
          <CardHeader
            title="Your plan's limits"
            description={ent.source === "no_plan" ? "You're not on a plan yet — these are your starting limits until you choose one." : ent.source === "override" ? "Your account has a custom setup from BlackSync." : undefined}
          />
          <Usage ent={ent} />
          {ent.over_limit.includes("agents") && (
            <div className="px-6 pb-5">
              <Notice tone="amber">
                You have more active agents than your plan allows. Nothing was deleted — the newest agents can&apos;t place calls until you pause some, add slots or upgrade.
              </Notice>
            </div>
          )}
        </Card>
      )}

      {live && current.plan_key && !managedNow && canManage && (
        <Card>
          <div id="agent-slots" />
          <CardHeader title="Extra agent slots" description={`${usd(data.agent_addon.amount_cents, 0)}/month each — adds one more active agent to your plan.`} />
          <div className="flex flex-wrap items-center justify-between gap-4 px-6 pb-5">
            <div className="text-sm text-zinc-600">
              You have <strong>{current.agent_slots ?? 0}</strong> extra slot{current.agent_slots === 1 ? "" : "s"}
              {ent?.limits.agents != null && <> · {ent.limits.agents} active agents allowed in total</>}.
            </div>
            <div className="flex items-center gap-2">
              <Button className="rounded-full!" disabled={!data.agent_addon.available || !current.agent_slots || busy === "slots"} onClick={() => void previewSlots((current.agent_slots ?? 0) - 1)}>
                <Minus className="h-4 w-4" /> Remove one
              </Button>
              <Button className="rounded-full!" variant="primary" disabled={!data.agent_addon.available || busy === "slots"} onClick={() => void previewSlots((current.agent_slots ?? 0) + 1)}>
                <Plus className="h-4 w-4" /> Add a slot
              </Button>
            </div>
          </div>
          {!data.agent_addon.available && <p className="px-6 pb-5 text-xs text-zinc-500">Agent slots aren&apos;t available to buy yet.</p>}
        </Card>
      )}

      {live && canManage && (
        <Card className="flex flex-wrap items-center justify-between gap-3 rounded-2xl p-5">
          <div className="text-sm text-zinc-600">
            {current.cancel_at_period_end ? (
              <>Your plan ends on <strong>{fmtDate(current.current_period_end)}</strong>.</>
            ) : (
              <>Renews on <strong>{fmtDate(current.current_period_end)}</strong>.</>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button className="rounded-full!" onClick={() => void portal()} loading={busy === "portal"}>
              <ExternalLink className="h-4 w-4" /> Manage in Stripe
            </Button>
            {current.cancel_at_period_end ? (
              <Button className="rounded-full!" variant="primary" onClick={() => void cancel(true)} loading={busy === "cancel"}>
                Keep my plan
              </Button>
            ) : (
              <Button className="rounded-full!" onClick={() => void cancel(false)} loading={busy === "cancel"}>
                Cancel plan
              </Button>
            )}
          </div>
        </Card>
      )}

      <Modal open={!!preview} onClose={() => setPreview(null)} title={preview ? `Switch to ${preview.plan.name}?` : ""}>
        {preview && (
          <div className="space-y-4 text-sm">
            <dl className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              <div className="flex justify-between px-4 py-2.5">
                <dt className="text-zinc-500">New price</dt>
                <dd className="font-medium">{usd(preview.data.new_monthly_cents)} / month</dd>
              </div>
              {preview.data.upgrade ? (
                <div className="flex justify-between px-4 py-2.5">
                  <dt className="text-zinc-500">Charged now (prorated)</dt>
                  <dd className="font-medium">{usd(preview.data.amount_due_now_cents)}</dd>
                </div>
              ) : (
                <div className="px-4 py-2.5 text-zinc-600">Unused time on your current plan is credited toward your next invoice.</div>
              )}
              {preview.data.included_credits_now > 0 && (
                <div className="flex justify-between px-4 py-2.5">
                  <dt className="text-zinc-500">Extra included credits now</dt>
                  <dd className="font-medium">+{preview.data.included_credits_now.toLocaleString()}</dd>
                </div>
              )}
              {!!preview.data.downgrade_effects?.length && (
                <div className="space-y-1 px-4 py-2.5 text-amber-800">
                  {preview.data.downgrade_effects.map((x) => (
                    <p key={x}>• {x}</p>
                  ))}
                </div>
              )}
              <div className="flex justify-between px-4 py-2.5">
                <dt className="text-zinc-500">Next invoice</dt>
                <dd>
                  {usd(preview.data.next_invoice_total_cents)} on {fmtDate(preview.data.next_period_end)}
                </dd>
              </div>
            </dl>
            <div className="flex justify-end gap-2">
              <Button className="rounded-full!" onClick={() => setPreview(null)}>Keep current plan</Button>
              <Button className="rounded-full!" variant="primary" loading={confirming} onClick={() => void confirmChange()}>
                Confirm and switch
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!slots} onClose={() => setSlots(null)} title={slots ? (slots.quantity > slots.current ? "Add an agent slot?" : "Remove an agent slot?") : ""}>
        {slots && (
          <div className="space-y-4 text-sm text-zinc-900">
            <dl className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              <div className="flex justify-between px-4 py-2.5">
                <dt className="text-zinc-500">Extra slots</dt>
                <dd className="font-medium">{slots.current} → {slots.quantity}</dd>
              </div>
              <div className="flex justify-between px-4 py-2.5">
                <dt className="text-zinc-500">Monthly change</dt>
                <dd className="font-medium">{slots.monthly_change_cents >= 0 ? "+" : "−"}{usd(Math.abs(slots.monthly_change_cents))} / month</dd>
              </div>
              {slots.agent_limit != null && (
                <div className="flex justify-between px-4 py-2.5">
                  <dt className="text-zinc-500">Active agents allowed</dt>
                  <dd className="font-medium">{slots.agent_limit}</dd>
                </div>
              )}
              <div className="px-4 py-2.5 text-zinc-600">{slots.proration}</div>
              {slots.over_after && (
                <div className="px-4 py-2.5 text-amber-800">
                  You have {slots.active_agents} active agents. No agent is deleted, but the newest ones can&apos;t call until you pause some.
                </div>
              )}
            </dl>
            <div className="flex justify-end gap-2">
              <Button className="rounded-full!" onClick={() => setSlots(null)}>Cancel</Button>
              <Button className="rounded-full!" variant="primary" loading={confirming} onClick={() => void applySlots()}>
                {slots.quantity > slots.current ? `Pay and add` : "Remove slot"}
              </Button>
            </div>
          </div>
        )}
      </Modal>
      <CountryPopup
        initial={countryData?.country}
        open={askCountry !== null}
        onDone={(country) => { const plan = askCountry; setAskCountry(null); if (plan) void choose(plan, country); }}
        onCancel={() => setAskCountry(null)}
      />
    </div>
  );
}
