"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Card, Notice } from "@/components/ui";
import { fetcher, post } from "@/lib/api";

type DeliveryStatus = { pending: number; sent: number; blocked: number };

export function BlackSyncDeliveryStatus() {
  const { data, error, mutate } = useSWR<DeliveryStatus>(
    "/api/integrations/crm/blacksync_cloud/deliveries",
    fetcher,
    { refreshInterval: 15000 },
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function retry() {
    setBusy(true);
    setMessage("");
    try {
      const result = await post<{ queued: number }>(
        "/api/integrations/crm/blacksync_cloud/deliveries/retry",
      );
      await mutate();
      setMessage(`${result.queued} deliveries queued for retry.`);
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Could not queue retries.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="space-y-3 p-5">
      <h2 className="font-medium">Call delivery to BlackSync Cloud</h2>
      <p className="text-sm text-zinc-500">
        Completed phone calls are picked up within about a minute. Failed
        deliveries stay saved for retry. Private recordings remain accessible
        through the authenticated source-call link.
      </p>
      {error ? (
        <Notice tone="red">Could not load delivery status.</Notice>
      ) : !data ? (
        <p className="text-sm">Loading delivery status…</p>
      ) : (
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <span>{data.sent} processed</span>
          <span>{data.pending} pending</span>
          <span>{data.blocked} need attention</span>
          {data.blocked > 0 && (
            <Button size="sm" loading={busy} onClick={retry}>
              Retry deliveries
            </Button>
          )}
        </div>
      )}
      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}
    </Card>
  );
}
