"use client";

import { Coins, Infinity as InfinityIcon, Receipt } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { Badge, Card, CardHeader, EmptyState, Notice, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { CreditHistory, CreditTransaction } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

const KIND: Record<CreditTransaction["kind"], { label: string; tone: "green" | "gray" | "amber" }> = {
  grant: { label: "Added", tone: "green" },
  usage: { label: "Call", tone: "gray" },
  adjustment: { label: "Adjustment", tone: "amber" },
};

const fmt = (n: number) => n.toLocaleString();

export function BillingTab() {
  const { data, error } = useSWR<CreditHistory>("/api/account/credits", fetcher);

  if (error) return <Card><EmptyState icon={<Coins className="h-5 w-5" />} title="Couldn't load credits" description={error.message} /></Card>;
  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  const low = !data.unlimited && data.balance <= 10;

  return (
    <div className="space-y-6">
      <Card className="p-5 sm:p-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">Calling credits</div>
            <div className="mt-1 flex items-baseline gap-2">
              {data.unlimited ? (
                <span className="flex items-center gap-2 text-3xl font-semibold tracking-tight text-zinc-900">
                  <InfinityIcon className="h-7 w-7 text-brand-600" /> Unlimited
                </span>
              ) : (
                <>
                  <span className={cn("text-4xl font-semibold tabular-nums tracking-tight", low ? "text-amber-700" : "text-zinc-900")}>
                    {fmt(data.balance)}
                  </span>
                  <span className="text-sm text-zinc-500">{data.balance === 1 ? "credit" : "credits"}</span>
                </>
              )}
            </div>
            {!data.unlimited && <div className="mt-0.5 text-xs text-zinc-500">≈ {fmt(Math.max(0, data.balance))} minutes of phone calls</div>}
          </div>
          <span className="brand-gradient hidden h-12 w-12 shrink-0 items-center justify-center rounded-xl text-white sm:flex">
            <Coins className="h-6 w-6" />
          </span>
        </div>
        <p className="mt-4 max-w-2xl text-xs leading-relaxed text-zinc-500">
          1 credit = 1 minute of phone calling. Billed per started minute from when the call is answered — ringing and unanswered calls are free.
          Browser test calls are free.
        </p>
        {low && (
          <div className="mt-4">
            <Notice tone="amber">Running low — contact your BlackSync admin to add credits.</Notice>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Credit history" description="Every credit added to or used by this account." />
        {data.transactions.length === 0 ? (
          <EmptyState icon={<Receipt className="h-5 w-5" />} title="No activity yet" description="Credits added and phone calls charged will show up here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="border-b border-zinc-100 text-left text-xs text-zinc-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Date</th>
                  <th className="px-5 py-3 font-medium">Description</th>
                  <th className="px-5 py-3 font-medium">Type</th>
                  <th className="px-5 py-3 text-right font-medium">Amount</th>
                  <th className="px-5 py-3 text-right font-medium">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {data.transactions.map((t) => {
                  const kind = KIND[t.kind] ?? { label: t.kind, tone: "gray" as const };
                  const desc = t.note || kind.label;
                  return (
                    <tr key={t.id} className="hover:bg-zinc-50">
                      <td className="whitespace-nowrap px-5 py-3 text-xs text-zinc-500">{formatDateTime(t.created_at)}</td>
                      <td className="max-w-[18rem] px-5 py-3">
                        {t.call_id ? (
                          <Link href={`/calls/${t.call_id}`} className="block truncate text-zinc-800 hover:text-brand-700 hover:underline">
                            {desc}
                          </Link>
                        ) : (
                          <span className="block truncate text-zinc-800">{desc}</span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <Badge tone={kind.tone}>{kind.label}</Badge>
                      </td>
                      <td
                        className={cn(
                          "whitespace-nowrap px-5 py-3 text-right font-medium tabular-nums",
                          t.amount > 0 ? "text-emerald-700" : "text-zinc-700",
                        )}
                      >
                        {t.amount > 0 ? `+${fmt(t.amount)}` : t.amount < 0 ? `−${fmt(Math.abs(t.amount))}` : "0"}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums text-zinc-500">{fmt(t.balance_after)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
