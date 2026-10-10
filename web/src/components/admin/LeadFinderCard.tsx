"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Card, CardHeader, Field, Input, Spinner, Toggle } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher, patch, post } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface Stats {
  enabled: boolean;
  credits: number;
  unlimited: boolean;
  last_30_days: { lookups: number; matches: number; cost: number; failed: number; bulk_files: number };
  ledger: { amount: number; balance_after: number; kind: string; note: string; at: string | null }[];
  recent_errors: { code: string | null; message: string | null; at: string | null }[];
}

const ERROR_LABEL: Record<string, string> = {
  auth: "API key rejected",
  balance: "Provider balance too low",
  rate_limited: "Rate limited by provider",
  provider_error: "Provider error",
  network: "Network / timeout",
  invalid_request: "Address rejected",
  interrupted: "Interrupted",
  internal: "Internal error",
};

/** Admin: one account's lead-lookup credits (separate from calling credits), usage, cost and errors. No contact data. */
export function LeadFinderCard({ orgId }: { orgId: string }) {
  const toast = useToast();
  const url = `/api/admin/orgs/${orgId}/lead-finder`;
  const { data, mutate } = useSWR<Stats>(url, fetcher);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function setFlag(body: Record<string, boolean>, msg: string) {
    try {
      await patch(`/api/admin/orgs/${orgId}`, body);
      await mutate();
      toast(msg);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function grant(sign: 1 | -1) {
    const n = Number(amount);
    if (!Number.isInteger(n) || n <= 0) return toast("Enter a whole number of credits.", "error");
    setSaving(true);
    try {
      const r = await post<{ credits: number }>(`/api/admin/orgs/${orgId}/lead-credits`, { amount: sign * n, note });
      setAmount("");
      setNote("");
      await mutate();
      toast(`Lookup credits: ${r.credits.toLocaleString()}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="min-w-0">
      <CardHeader title="Lead Finder" description="Lookup credits — separate from calling credits" />
      {!data ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="flex flex-col gap-4 p-5">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-xs text-zinc-500">Lookup credits</span>
            <span className="font-display text-2xl font-semibold tabular-nums">{data.unlimited ? "Unlimited" : data.credits.toLocaleString()}</span>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Credits" className="w-28">
              <Input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="numeric" placeholder="100" />
            </Field>
            <Field label="Note (optional)" className="min-w-0 flex-1">
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Monthly pack" maxLength={500} />
            </Field>
            <Button size="sm" variant="primary" onClick={() => grant(1)} loading={saving}>
              Add
            </Button>
            <Button size="sm" variant="ghost" onClick={() => grant(-1)} disabled={saving}>
              Remove
            </Button>
          </div>
          <Toggle label="Unlimited lookup credits" description="For house accounts. Provider costs still apply." checked={data.unlimited} onChange={(v) => setFlag({ lead_credits_unlimited: v }, v ? "Unlimited on" : "Unlimited off")} />
          <Toggle label="Lead Finder enabled" description="When off, this account can't run new lookups." checked={data.enabled} onChange={(v) => setFlag({ lead_finder_enabled: v }, v ? "Lead Finder enabled" : "Lead Finder disabled")} />

          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-zinc-500">Lookups (30d)</dt>
              <dd className="font-medium tabular-nums">{data.last_30_days.lookups}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">Owners found</dt>
              <dd className="font-medium tabular-nums">{data.last_30_days.matches}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">Bulk files</dt>
              <dd className="font-medium tabular-nums">{data.last_30_days.bulk_files}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">Provider cost</dt>
              <dd className="font-medium tabular-nums">${data.last_30_days.cost.toFixed(2)}</dd>
            </div>
          </dl>

          {data.ledger.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-zinc-700">Credit history</div>
              <ul className="max-h-48 space-y-1 overflow-y-auto text-xs">
                {data.ledger.map((t, i) => (
                  <li key={i} className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate text-zinc-700">{t.note || t.kind}</span>
                    <span className="shrink-0 tabular-nums">
                      <span className={t.amount > 0 ? "text-emerald-700" : "text-zinc-700"}>
                        {t.amount > 0 ? "+" : ""}
                        {t.amount}
                      </span>
                      <span className="ml-2 text-zinc-400">{t.at ? timeAgo(t.at) : ""}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.recent_errors.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-zinc-700">Recent errors</div>
              <ul className="space-y-1 text-xs">
                {data.recent_errors.map((e, i) => (
                  <li key={i} className="flex justify-between gap-3">
                    <span className="text-zinc-700">{ERROR_LABEL[e.code ?? ""] ?? e.code ?? "Error"}</span>
                    <span className="shrink-0 text-zinc-400">{e.at ? timeAgo(e.at) : ""}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
