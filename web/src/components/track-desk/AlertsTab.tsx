"use client";

import { BellRing, Check, Phone } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { ALERT_LABEL, type Alert } from "./types";

const TONE: Record<string, "red" | "amber" | "violet" | "gray"> = {
  late: "red", unresponsive: "red", at_risk: "amber", driver_requested_human: "violet", dnc: "gray", needs_review: "amber",
};

/** Track Desk → Alerts: the exceptions to act on (late, unresponsive, driver asked for a person…). */
export function AlertsTab() {
  const toast = useToast();
  const [showAll, setShowAll] = useState(false);
  const { data, error, mutate } = useSWR<{ items: Alert[] }>(
    `/api/track-desk/alerts?include_acknowledged=${showAll}`, fetcher, { refreshInterval: 30000 },
  );
  const open = data?.items.filter((a) => !a.acknowledged_at).length ?? 0;

  async function ack(id?: string) {
    try {
      await post(id ? `/api/track-desk/alerts/${id}/acknowledge` : "/api/track-desk/alerts/acknowledge-all");
      await mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-zinc-600">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} className="rounded border-zinc-300" />
          Show acknowledged
        </label>
        {open > 1 && <Button size="sm" className="ml-auto" onClick={() => ack()}><Check className="h-3.5 w-3.5" /> Acknowledge all</Button>}
      </div>
      {error ? (
        <Card><EmptyState icon={<BellRing className="h-5 w-5" />} title="Couldn't load alerts" description={error.message} /></Card>
      ) : !data ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : data.items.length === 0 ? (
        <Card><EmptyState icon={<BellRing className="h-5 w-5" />} title="No alerts" description="You'll hear here (and by email or text) only when a load is late, at risk or the driver can't be reached." /></Card>
      ) : (
        <Card className="divide-y divide-zinc-100 overflow-hidden p-0">
          {data.items.map((a) => (
            <div key={a.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={TONE[a.kind] ?? "gray"}>{ALERT_LABEL[a.kind] ?? a.kind}</Badge>
                  <Link href={`/track-desk/${a.load}`} className="font-semibold text-zinc-900 hover:underline">Load {a.load_id}</Link>
                  <span className="text-xs text-zinc-500">{timeAgo(a.sent_at)}</span>
                  {a.delivered_via.filter((v) => v !== "in_app").map((v) => <Badge key={v}>{v === "sms" ? "Texted" : "Emailed"}</Badge>)}
                </div>
                <p className="mt-1.5 whitespace-pre-line text-sm text-zinc-700">{a.message}</p>
                {a.acknowledged_at && <p className="mt-1 text-xs text-zinc-500">Acknowledged {timeAgo(a.acknowledged_at)}{a.acknowledged_by ? ` by ${a.acknowledged_by}` : ""}</p>}
              </div>
              <div className="flex shrink-0 gap-2">
                {a.driver_phone && <a href={`tel:${a.driver_phone}`}><Button size="sm"><Phone className="h-3.5 w-3.5" /> Call driver</Button></a>}
                {!a.acknowledged_at && <Button size="sm" variant="primary" onClick={() => ack(a.id)}>Acknowledge</Button>}
              </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
