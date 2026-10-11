"use client";

import { CreditCard, Download, ExternalLink } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Notice, Spinner } from "@/components/ui";
import { Card, CardHeader, emptyCls, listCls, rowCls } from "./surface";
import { cn } from "@/lib/utils";
import { fetcher, post } from "@/lib/api";
import { type Card as CardInfo, type Purchase, fmtDate, fmtDateTime, usd } from "./types";

interface Invoices {
  purchases: Purchase[];
  invoices: { id: string; number: string | null; status: string; total_cents: number; created: string; hosted_url: string | null; pdf: string | null }[];
  card: CardInfo | null;
  has_billing_profile: boolean;
  stripe_ready: boolean;
  error?: string;
}

const PURCHASE_LABEL: Record<Purchase["kind"], string> = {
  credit_pack: "Calling credits", lookup_funds: "Lead lookup funds", auto_recharge: "Auto-recharge",
};

const STATUS_TONE: Record<string, "green" | "amber" | "red" | "gray"> = {
  paid: "green", pending: "amber", failed: "red", canceled: "gray", refunded: "gray", partially_refunded: "amber", disputed: "red",
  open: "amber", void: "gray", uncollectible: "red", draft: "gray",
};

export function InvoicesTab({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data } = useSWR<Invoices>("/api/billing/invoices", fetcher);
  const [opening, setOpening] = useState(false);

  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  async function portal() {
    setOpening(true);
    try {
      window.location.href = (await post<{ url: string }>("/api/billing/portal")).url;
    } catch (e) {
      toast((e as Error).message, "error");
      setOpening(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card className="flex flex-wrap items-center justify-between gap-4 p-6">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-zinc-100">
            <CreditCard className="h-5 w-5 text-zinc-500" />
          </span>
          <div>
            <div className="text-sm font-medium text-zinc-900">
              {data.card ? `${(data.card.brand ?? "Card").replace(/^\w/, (c) => c.toUpperCase())} ending ${data.card.last4}` : "No saved payment method"}
            </div>
            <div className="text-xs text-zinc-500">
              {data.card ? `Expires ${data.card.exp_month}/${data.card.exp_year}` : "A card is saved when you make your first purchase."}
            </div>
          </div>
        </div>
        {canManage && data.has_billing_profile && (
          <Button className="rounded-full!" onClick={() => void portal()} loading={opening}>
            <ExternalLink className="h-4 w-4" /> Update payment method
          </Button>
        )}
      </Card>
      <p className="-mt-3 text-xs text-zinc-500">Cards are handled by Stripe — BlackSync never sees or stores your card number.</p>

      {data.error && <Notice>{data.error}</Notice>}

      <Card className="min-w-0">
        <CardHeader title="Invoices" description="Subscription and add-on invoices" />
        {data.invoices.length === 0 ? (
          <p className={emptyCls}>No invoices yet.</p>
        ) : (
          <ul className={listCls}>
            {data.invoices.map((i) => (
              <li key={i.id} className={cn("flex flex-wrap items-center gap-3", rowCls)}>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-zinc-800">{i.number ?? i.id}</span>
                  <span className="text-xs text-zinc-500">{fmtDate(i.created)}</span>
                </span>
                <Badge tone={STATUS_TONE[i.status] ?? "gray"}>{i.status}</Badge>
                <span className="w-20 text-right tabular-nums">{usd(i.total_cents)}</span>
                <span className="flex gap-2">
                  {i.hosted_url && (
                    <a href={i.hosted_url} target="_blank" rel="noreferrer" className="text-zinc-500 hover:text-zinc-900" aria-label="View invoice">
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  )}
                  {i.pdf && (
                    <a href={i.pdf} target="_blank" rel="noreferrer" className="text-zinc-500 hover:text-zinc-900" aria-label="Download PDF">
                      <Download className="h-4 w-4" />
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="min-w-0">
        <CardHeader title="One-time purchases" description="Credit packs, lookup funds and auto-recharges" />
        {data.purchases.length === 0 ? (
          <p className={emptyCls}>No purchases yet.</p>
        ) : (
          <ul className={listCls}>
            {data.purchases.map((p) => (
              <li key={p.id} className={cn("flex flex-wrap items-center gap-3", rowCls)}>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-zinc-800">
                    {PURCHASE_LABEL[p.kind]}
                    {p.credits ? ` — ${p.credits.toLocaleString()} credits` : ""}
                  </span>
                  <span className="text-xs text-zinc-500">
                    {fmtDateTime(p.created_at)}
                    {p.error ? ` · ${p.error}` : ""}
                  </span>
                </span>
                <Badge tone={STATUS_TONE[p.status] ?? "gray"}>{p.status.replace("_", " ")}</Badge>
                <span className="w-20 text-right tabular-nums">{usd(p.amount_cents)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
