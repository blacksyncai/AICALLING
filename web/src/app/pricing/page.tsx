"use client";

import Link from "next/link";
import { WebsiteLink } from "@/components/WebsiteLink";
import useSWR from "swr";
import { PlanCards } from "@/components/billing/PlanCards";
import type { BookingLinks, Plan } from "@/components/billing/types";
import { usd } from "@/components/billing/types";
import { Spinner } from "@/components/ui";
import { PricingHeading } from "@/components/ui/pricing";
import { fetcher } from "@/lib/api";

interface PublicPlans {
  plans: Plan[];
  packs: { key: string; name: string; credits: number; amount_cents: number; blurb: string }[];
  agent_addon: { amount_cents: number };
  phone_addon: { amount_cents: number };
  links: BookingLinks;
}

/** Public pricing (no sign-in). Plan facts come from the same server catalog Billing uses. */
export default function PricingPage() {
  const { data } = useSWR<PublicPlans>("/api/billing/public/plans", fetcher);
  return (
    <main className="app-canvas min-h-screen">
      <div className="mx-auto max-w-7xl px-4 py-10 sm:px-8 sm:py-14">
        <div className="mb-8 flex items-center justify-between">
          <span className="font-display text-lg font-semibold text-zinc-900">BlackSync AI</span>
          <span className="flex items-center gap-4">
          <WebsiteLink />
          <Link href="/sign-up" className="rounded-full bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">
            Create your account
          </Link>
          </span>
        </div>
        <PricingHeading title="Simple plans for AI calling" description="Every plan includes calling credits each month and every core feature. Need more? Credits, agent slots and numbers can be added any time." />
        {!data ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : (
          <>
            <PlanCards
              plans={data.plans}
              action={(p) => (p.self_serve ? { label: `Start with ${p.name}`, href: `/sign-up?plan=${p.key}` } : { label: "Contact Sales", href: data.links.sales_booking_url })}
            />
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              <div className="rounded-2xl bg-white p-5 ring-1 ring-zinc-900/[0.06]">
                <h3 className="font-semibold text-zinc-900">Calling credit packs</h3>
                <p className="mt-1 text-sm text-zinc-600">Never expire. Used after your monthly credits.</p>
                <ul className="mt-3 space-y-1 text-sm text-zinc-700">
                  {data.packs.map((p) => (
                    <li key={p.key} className="flex justify-between">
                      <span>{p.credits.toLocaleString()} credits</span>
                      <span className="font-medium">{usd(p.amount_cents, 0)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-2xl bg-white p-5 ring-1 ring-zinc-900/[0.06]">
                <h3 className="font-semibold text-zinc-900">Extra agent slot</h3>
                <p className="mt-1 text-sm text-zinc-600">{usd(data.agent_addon.amount_cents, 0)}/month each, on any plan. Adds one more active agent.</p>
              </div>
              <div className="rounded-2xl bg-white p-5 ring-1 ring-zinc-900/[0.06]">
                <h3 className="font-semibold text-zinc-900">Extra phone numbers</h3>
                <p className="mt-1 text-sm text-zinc-600">{usd(data.phone_addon.amount_cents)}/month each beyond the numbers your plan includes.</p>
              </div>
            </div>
            <p className="mt-6 text-xs text-zinc-500">
              A credit is about one minute of calling on Standard models (Premium models use a little more). Prices in USD; taxes may apply.
              Managed includes the setup listed — additional development is quoted separately.
            </p>
          </>
        )}
      </div>
    </main>
  );
}
