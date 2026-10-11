"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Card, Modal, Notice, Spinner } from "@/components/ui";
import { PillBadge, PricingButton, PricingCard, PricingHeading } from "@/components/ui/pricing";
import { fetcher, post } from "@/lib/api";
import { type Catalog, type Plan, fmtDate, usd } from "./types";

interface Preview {
  plan: string;
  upgrade: boolean;
  amount_due_now_cents: number;
  next_invoice_total_cents: number | null;
  next_period_end: string | null;
  new_monthly_cents: number;
  included_credits_now: number;
}

export function PlansTab({ canManage, refresh }: { canManage: boolean; refresh: () => void }) {
  const toast = useToast();
  const { data, mutate } = useSWR<Catalog>("/api/billing/catalog", fetcher);
  const [busy, setBusy] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ plan: Plan; data: Preview } | null>(null);
  const [confirming, setConfirming] = useState(false);

  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  const current = data.current_plan;
  const live = ["active", "trialing", "past_due"].includes(current.status);

  async function choose(plan: Plan) {
    setBusy(plan.key);
    try {
      if (!live) {
        const r = await post<{ url: string }>(`/api/billing/plans/${plan.key}/checkout`);
        window.location.href = r.url;
        return;
      }
      setPreview({ plan, data: await post<Preview>(`/api/billing/plans/${plan.key}/preview`) });
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function confirmChange() {
    if (!preview) return;
    setConfirming(true);
    try {
      await post(`/api/billing/plans/${preview.plan.key}/change`, { confirm: true });
      setPreview(null);
      await mutate();
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
      <PricingHeading title="A plan that fits your team" description="Every plan includes calling credits each month. Buy more any time — they never expire." />
      <div className="grid gap-4 md:grid-cols-2">
        {data.plans.map((p, i) => {
          const isCurrent = live && current.plan_key === p.key;
          const featured = isCurrent || (!live && i === data.plans.length - 1);
          return (
            <PricingCard
              key={p.key}
              index={i}
              name={p.name}
              description={`${p.included_credits.toLocaleString()} calling credits included every month`}
              cents={p.amount_cents}
              period={p.interval}
              highlighted={featured}
              badge={isCurrent ? <PillBadge tone="dark">Current plan</PillBadge> : featured ? <PillBadge>Best value</PillBadge> : null}
              featuresTitle="Includes"
              features={p.features}
              footer={
                isCurrent ? (
                  <PricingButton tone="muted" disabled>
                    Current plan
                  </PricingButton>
                ) : (
                  <PricingButton
                    tone={featured ? "brand" : "dark"}
                    loading={busy === p.key}
                    disabled={!canManage || !p.available || !!busy || (live && current.managed === false)}
                    onClick={() => void choose(p)}
                  >
                    {!p.available ? "Not available yet" : live ? `Switch to ${p.name}` : `Choose ${p.name}`}
                  </PricingButton>
                )
              }
            />
          );
        })}
      </div>
      <p className="text-xs text-zinc-500">
        Included credits are added each time a billing period is paid and expire at the end of it. Credits you buy separately never expire. Prices in USD; taxes may apply.
      </p>

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
            <Button onClick={() => void portal()} loading={busy === "portal"}>
              <ExternalLink className="h-4 w-4" /> Manage in Stripe
            </Button>
            {current.cancel_at_period_end ? (
              <Button variant="primary" onClick={() => void cancel(true)} loading={busy === "cancel"}>
                Keep my plan
              </Button>
            ) : (
              <Button onClick={() => void cancel(false)} loading={busy === "cancel"}>
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
              <div className="flex justify-between px-4 py-2.5">
                <dt className="text-zinc-500">Next invoice</dt>
                <dd>
                  {usd(preview.data.next_invoice_total_cents)} on {fmtDate(preview.data.next_period_end)}
                </dd>
              </div>
            </dl>
            <div className="flex justify-end gap-2">
              <Button onClick={() => setPreview(null)}>Keep current plan</Button>
              <Button variant="primary" loading={confirming} onClick={() => void confirmChange()}>
                Confirm and switch
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
