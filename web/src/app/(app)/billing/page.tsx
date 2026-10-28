"use client";

import { Coins, CreditCard, LayoutGrid, Phone, Receipt, UserSearch } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import MatteAlertFeedback from "@/components/ui/matte-alert-feedback";
import type { AutoRechargeCfg, CreditBreakdown } from "@/components/billing/types";
import { CreditsTab } from "@/components/billing/CreditsTab";
import { InvoicesTab } from "@/components/billing/InvoicesTab";
import { LookupsTab } from "@/components/billing/LookupsTab";
import { OverviewTab } from "@/components/billing/OverviewTab";
import { PlansTab } from "@/components/billing/PlansTab";
import { PhoneNumbersTab } from "@/components/billing/PhoneNumbersTab";
import type { Overview, Purchase } from "@/components/billing/types";
import { Notice, PageHeader, Spinner } from "@/components/ui";
import { PillTabs } from "@/components/ui/pricing";
import { api, fetcher } from "@/lib/api";

const TABS = [
  { value: "overview", label: "Overview", icon: LayoutGrid },
  { value: "plans", label: "Plans", icon: CreditCard },
  { value: "credits", label: "Calling Credits", icon: Coins },
  { value: "numbers", label: "Phone Numbers", icon: Phone },
  { value: "lookups", label: "Lead Lookup Balance", icon: UserSearch },
  { value: "invoices", label: "Invoices & Payments", icon: Receipt },
] as const;

type Tab = (typeof TABS)[number]["value"];

function CheckoutReturn() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { mutate } = useSWRConfig();
  const state = params.get("checkout");
  const purchaseId = params.get("purchase");
  const [purchase, setPurchase] = useState<Purchase | null>(null);
  const [gaveUp, setGaveUp] = useState(false);

  useEffect(() => {
    if (state !== "success" || !purchaseId) return;
    let stop = false;
    let tries = 0;
    async function poll() {
      try {
        const p = await api<Purchase>(`/api/billing/purchases/${purchaseId}`);
        if (stop) return;
        setPurchase(p);
        if (p.status !== "pending") {
          void mutate((key) => typeof key === "string" && (key.startsWith("/api/billing") || key === "/api/auth/me"));
          return;
        }
      } catch {
        /* keep polling */
      }
      if (++tries < 20) setTimeout(poll, 1500);
      else setGaveUp(true);
    }
    void poll();
    return () => {
      stop = true;
    };
  }, [state, purchaseId, mutate]);

  if (!state) return null;
  const dismiss = () => {
    const p = new URLSearchParams(params.toString());
    p.delete("checkout");
    p.delete("purchase");
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  let body: React.ReactNode;
  let tone: "green" | "blue" | "amber" | "red" = "blue";
  if (state === "canceled") {
    body = "Checkout canceled — nothing was charged.";
    tone = "amber";
  } else if (!purchaseId) {
    body = "Thanks! Your subscription is being set up — it appears here within a few seconds.";
    tone = "green";
  } else if (purchase?.status === "paid") {
    body =
      purchase.kind === "lookup_funds"
        ? `Payment received — $${(purchase.amount_cents / 100).toFixed(2)} added to your lookup balance.`
        : `Payment received — ${purchase.credits.toLocaleString()} calling credits added.`;
    tone = "green";
  } else if (purchase?.status === "failed") {
    body = purchase.error || "The payment didn't go through. Nothing was added.";
    tone = "red";
  } else {
    body = gaveUp ? "Your payment is still processing. Credits are added as soon as it clears." : "Confirming your payment…";
  }
  return (
    <div className="mb-6">
      <Notice tone={tone}>
        <span className="flex items-center justify-between gap-3">
          <span>{body}</span>
          <button type="button" onClick={dismiss} className="shrink-0 text-xs font-medium underline">
            Dismiss
          </button>
        </span>
      </Notice>
    </div>
  );
}

function BillingContent() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: Tab = TABS.some((t) => t.value === raw) ? (raw as Tab) : "overview";
  const { data: overview, error, mutate } = useSWR<Overview>("/api/billing/overview", fetcher);
  const { data: credits } = useSWR<CreditBreakdown>("/api/billing/credits", fetcher);
  const { data: recharge } = useSWR<AutoRechargeCfg>("/api/billing/auto-recharge", fetcher);
  const lowCredits = !!credits && !credits.unlimited && credits.balance < 20 && recharge !== undefined && !recharge.enabled;

  function select(next: Tab) {
    const p = new URLSearchParams(params.toString());
    if (next === "overview") p.delete("tab");
    else p.set("tab", next);
    const qs = p.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  return (
    <>
      <PageHeader title="Billing & Usage" description="Your plan, calling credits, lead lookup balance and invoices." />
      <CheckoutReturn />
      <div className="mb-6">
        <PillTabs
          value={tab}
          onChange={select}
          layoutId="billing-tab"
          tabs={TABS.map((t) => ({ value: t.value, label: t.label, icon: <t.icon className="h-4 w-4" /> }))}
        />
      </div>
      {error ? (
        <Notice tone="red">{error.message}</Notice>
      ) : !overview ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : (
        <>
          {!overview.stripe_ready && (
            <div className="mb-6">
              <Notice>Online payments aren&apos;t switched on yet. Your balances and usage are shown below; purchases open once payments are set up.</Notice>
            </div>
          )}
          {lowCredits && tab !== "credits" && (
            <div className="mb-6 max-w-2xl">
              <MatteAlertFeedback
                cardTitle="Calling credits"
                pillText={`${Math.max(0, Math.floor(credits!.balance))} left`}
                cardDescription="Campaigns pause automatically when credits run out."
                alertTitle="Running low on credits"
                alertDetail="Turn on auto-recharge to top up automatically, or buy a pack now."
                showControls={false}
                action={
                  <button type="button" onClick={() => select("credits")} className="inline-flex h-8 items-center rounded-lg bg-brand-600 px-3 text-xs font-medium text-white hover:bg-brand-700">
                    Set up auto-recharge
                  </button>
                }
              />
            </div>
          )}
          {tab === "overview" && <OverviewTab overview={overview} go={select} />}
          {tab === "plans" && <PlansTab canManage={overview.can_manage} refresh={() => void mutate()} />}
          {tab === "credits" && <CreditsTab canManage={overview.can_manage} />}
          {tab === "numbers" && <PhoneNumbersTab />}
          {tab === "lookups" && <LookupsTab canManage={overview.can_manage} />}
          {tab === "invoices" && <InvoicesTab canManage={overview.can_manage} />}
        </>
      )}
    </>
  );
}

export default function BillingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      }
    >
      <BillingContent />
    </Suspense>
  );
}
