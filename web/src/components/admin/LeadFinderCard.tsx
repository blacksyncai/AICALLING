"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Button, Card, CardHeader, Field, Input, Spinner, Toggle } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher, patch } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface Stats {
  enabled: boolean;
  daily_limit: number;
  limit_is_default: boolean;
  default_limit: number;
  used_today: number;
  last_30_days: { lookups: number; matches: number; cost: number; failed: number };
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

/** Admin: one account's Lead Finder usage, cost, errors, daily allowance and on/off. No contact data. */
export function LeadFinderCard({ orgId }: { orgId: string }) {
  const toast = useToast();
  const url = `/api/admin/orgs/${orgId}/lead-finder`;
  const { data, mutate } = useSWR<Stats>(url, fetcher);
  const [limit, setLimit] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => setLimit(data ? String(data.daily_limit) : ""), [data]);

  async function save(body: Record<string, unknown>, msg: string) {
    setSaving(true);
    try {
      await patch(`/api/admin/orgs/${orgId}`, body);
      await mutate();
      toast(msg);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="min-w-0">
      <CardHeader title="Lead Finder" description="Property-owner lookups (DataSkip)" />
      {!data ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="flex flex-col gap-4 p-5">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-zinc-500">Used today</dt>
              <dd className="font-medium tabular-nums">
                {data.used_today} / {data.daily_limit}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">Lookups (30d)</dt>
              <dd className="font-medium tabular-nums">{data.last_30_days.lookups}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">Matches (30d)</dt>
              <dd className="font-medium tabular-nums">{data.last_30_days.matches}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">Provider cost (30d)</dt>
              <dd className="font-medium tabular-nums">${data.last_30_days.cost.toFixed(2)}</dd>
            </div>
          </dl>
          <Toggle
            label="Lead Finder enabled"
            description="When off, this account can't run new lookups."
            checked={data.enabled}
            onChange={(v) => save({ lead_finder_enabled: v }, v ? "Lead Finder enabled" : "Lead Finder disabled")}
          />
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const n = Number(limit);
              if (!Number.isInteger(n) || n < 0) return toast("Enter a whole number of lookups.", "error");
              void save({ lead_finder_daily_limit: n }, "Daily allowance updated");
            }}
          >
            <Field label="Daily lookups" hint={data.limit_is_default ? `Platform default (${data.default_limit})` : "Custom for this account"} className="w-36">
              <Input value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="numeric" />
            </Field>
            <Button type="submit" size="sm" loading={saving}>
              Save
            </Button>
            {!data.limit_is_default && (
              <Button type="button" size="sm" variant="ghost" onClick={() => save({ lead_finder_daily_limit: -1 }, "Back to the platform default")}>
                Use default
              </Button>
            )}
          </form>
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
