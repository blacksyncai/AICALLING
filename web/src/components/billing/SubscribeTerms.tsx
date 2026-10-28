"use client";

import { ArrowUpRight, Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Modal } from "@/components/ui";
import { TERMS_PATH } from "@/lib/terms";
import { type Plan, usd } from "./types";

const PER: Record<string, string> = { month: "month", year: "year", week: "week" };
const BILLED: Record<string, string> = { month: "Billed monthly", year: "Billed yearly", week: "Billed weekly" };

/** The last step before a first subscription's checkout: what will be charged, how often, how to cancel,
 *  and an explicit (unticked) agreement to the Terms and recurring charges. The server checks it again. */
export function SubscribeTerms({ plan, onClose, onConfirm, busy }: {
  plan: Plan | null; onClose: () => void; onConfirm: () => void; busy: boolean;
}) {
  const [agreed, setAgreed] = useState(false);
  useEffect(() => setAgreed(false), [plan?.key]);
  if (!plan) return null;
  const interval = plan.interval || "month";

  return (
    <Modal open={!!plan} onClose={() => !busy && onClose()} title={`Start ${plan.name}`}>
      <div className="space-y-4 text-sm">
        <dl className="divide-y divide-zinc-100 rounded-xl border border-zinc-200">
          <div className="flex items-baseline justify-between gap-3 px-4 py-3">
            <dt className="text-zinc-500">Price</dt>
            <dd className="text-right">
              <span className="text-base font-semibold text-zinc-900">{usd(plan.amount_cents ?? 0)}</span>
              <span className="text-zinc-500"> / {PER[interval] ?? interval}</span>
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-3 px-4 py-3">
            <dt className="text-zinc-500">Billing</dt>
            <dd className="text-right text-zinc-800">{BILLED[interval] ?? `Billed every ${interval}`}, renews automatically</dd>
          </div>
          <div className="px-4 py-3">
            <dt className="text-zinc-500">Cancellation</dt>
            <dd className="mt-1 text-zinc-700">
              Cancel anytime in Billing before your next billing date. Access continues through the current paid period. Payments are
              nonrefundable except where required by law.
            </dd>
          </div>
        </dl>

        <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-zinc-50 p-3 ring-1 ring-zinc-900/5">
          <input
            type="checkbox"
            required
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-brand-600"
            aria-describedby="terms-note"
          />
          <span className="text-zinc-800">
            I agree to the{" "}
            <a href={TERMS_PATH} target="_blank" rel="noopener" className="inline-flex items-center gap-0.5 font-medium text-brand-700 underline-offset-2 hover:underline">
              Terms of Service
              <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
            </a>{" "}
            and authorize recurring subscription charges according to the plan selected.
          </span>
        </label>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span id="terms-note" className="inline-flex items-center gap-1.5 text-xs text-zinc-500">
            <Lock className="h-3 w-3" /> You pay on the next, secure page.
          </span>
          <div className="ml-auto flex gap-2">
            <Button className="rounded-full!" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button className="whitespace-nowrap rounded-full!" variant="primary" disabled={!agreed} loading={busy} onClick={onConfirm}>
              Continue to payment
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
