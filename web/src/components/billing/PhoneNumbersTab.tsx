"use client";

import { ArrowRight, Phone } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { NumberPackCard } from "@/components/phone/NumberPackCard";
import { fetcher } from "@/lib/api";
import type { MyPhoneNumbers } from "@/lib/types";

/** Billing → Phone Numbers: the two ways to pay for caller numbers, side by side. */
export function PhoneNumbersTab() {
  const { data, mutate } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher);
  const p = data?.pricing;
  const unit = p ? `$${(p.unit_cents / 100).toFixed(2)}` : "$3.50";
  const regular = p?.active ?? 0;
  const extra = p?.subscribed ? Math.max(0, regular - p.included) : 0;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="flex flex-col rounded-2xl bg-white shadow-xs ring-1 ring-zinc-900/5">
        <div className="flex flex-1 flex-col gap-4 p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-zinc-900 text-white">
                  <Phone className="h-4 w-4" />
                </span>
                <h2 className="font-display text-lg font-semibold tracking-tight text-zinc-900">Single numbers</h2>
              </div>
              <p className="mt-2 text-sm text-zinc-600">A local number that stays yours: your caller ID, and the line contacts call back.</p>
            </div>
            <div className="shrink-0 text-right">
              <div className="font-display text-2xl font-semibold tabular-nums text-zinc-900">{unit}</div>
              <div className="text-xs text-zinc-500">per number / month</div>
            </div>
          </div>
          <dl className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 text-sm">
            <div className="flex justify-between px-4 py-2.5">
              <dt className="text-zinc-500">Your numbers</dt>
              <dd className="font-medium tabular-nums">{data ? regular : "…"}</dd>
            </div>
            <div className="flex justify-between px-4 py-2.5">
              <dt className="text-zinc-500">Included with your plan</dt>
              <dd className="font-medium tabular-nums">{p?.subscribed ? p.included : "No plan"}</dd>
            </div>
            <div className="flex justify-between px-4 py-2.5">
              <dt className="text-zinc-500">Billed as extra</dt>
              <dd className="font-medium tabular-nums">
                {extra} × {unit} = ${((extra * (p?.unit_cents ?? 350)) / 100).toFixed(2)}/mo
              </dd>
            </div>
          </dl>
          <p className="text-xs text-zinc-500">
            {p?.subscribed
              ? `Numbers past your plan's included ones are ${unit}/month each, charged prorated when added.`
              : `No plan needed: each number is ${unit}/month on its own. Plans include 1–4 numbers.`}
          </p>
          <Link href="/phone-numbers" className="mt-auto inline-flex items-center gap-1 self-start text-sm font-medium text-brand-700 hover:underline">
            Get or manage numbers <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>
      <NumberPackCard onChanged={() => void mutate()} pickHref="/phone-numbers#get-number" />
    </div>
  );
}
