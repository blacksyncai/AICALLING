"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { useToast } from "@/components/toast";
import { Card, CardHeader, Toggle } from "@/components/ui";
import { fetcher, put } from "@/lib/api";

/** Optional sections an account turns on: Track Desk (freight check calls) is off unless the account is freight. */
export function FeaturesCard({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { mutate: mutateAll } = useSWRConfig();
  const { data, mutate } = useSWR<{ enabled: boolean; freight_account: boolean }>("/api/track-desk/enabled", fetcher);
  const [busy, setBusy] = useState(false);
  if (!data) return null;

  async function set(enabled: boolean) {
    setBusy(true);
    try {
      await mutate(await put("/api/track-desk/enabled", { enabled }), { revalidate: false });
      await mutateAll((key) => typeof key === "string" && key.startsWith("/api/track-desk/enabled"));  // the sidebar
      toast(enabled ? "Track Desk is on" : "Track Desk is off");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Features" description="Extra sections for specific industries. Turned-off sections are hidden from your team." />
      <div className="p-5">
        <div className={busy || !canManage ? "pointer-events-none opacity-60" : ""}>
          <Toggle
            checked={data.enabled}
            onChange={set}
            label="Track Desk · freight check calls"
            description="For freight brokers: AI calls or texts your drivers for location and ETA and flags late loads. Adds Track Desk to the sidebar."
          />
        </div>
      </div>
    </Card>
  );
}
