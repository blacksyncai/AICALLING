"use client";

import { KeyRound, Webhook as WebhookIcon } from "lucide-react";
import useSWR from "swr";
import { ApiKeysCard } from "@/components/integrations/ApiKeysCard";
import { ZapierCard } from "@/components/integrations/ZapierCard";
import { WebhooksCard } from "@/components/integrations/WebhooksCard";
import { Card, Notice, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import type { Integrations } from "@/lib/types";

const DESCRIPTION = "Connect BlackSync to Zapier, Make, n8n, your CRM or your own code.";

function StatTile({ label, value, icon: Icon }: { label: string; value: number; icon: typeof KeyRound }) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0">
        <div className="truncate text-xs font-medium text-zinc-500">{label}</div>
        <div className="font-display text-xl font-semibold tabular-nums tracking-tight text-zinc-900">{value}</div>
      </div>
    </Card>
  );
}

export default function IntegrationsPage() {
  const { session, loading } = useSession();
  const allowed = canManage(session);
  const { data, error, mutate } = useSWR<Integrations>(allowed ? "/api/integrations" : null, fetcher);
  const refresh = () => void mutate();

  if (loading) {
    return (
      <>
        <PageHeader title="Integrations" description={DESCRIPTION} />
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      </>
    );
  }

  if (!allowed) {
    return (
      <>
        <PageHeader title="Integrations" description={DESCRIPTION} />
        <Notice tone="amber">Only account owners and admins can manage API keys and webhooks. Ask an admin on your team for access.</Notice>
      </>
    );
  }

  const activeWebhooks = data?.webhooks.filter((w) => w.active).length ?? 0;

  return (
    <>
      <PageHeader title="Integrations" description={DESCRIPTION} />
      {error && (
        <div className="mb-6">
          <Notice tone="red">Couldn&apos;t load integrations: {error.message}</Notice>
        </div>
      )}
      {!data && !error && (
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      )}
      {data && (
        <div className="min-w-0 space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-[1fr_1fr_2fr]">
            <StatTile label="Active webhooks" value={activeWebhooks} icon={WebhookIcon} />
            <StatTile label="Active API keys" value={data.api_keys.length} icon={KeyRound} />
            <div className="col-span-2 flex flex-wrap items-center gap-1.5 rounded-xl border border-dashed border-zinc-200 px-4 py-3 text-xs text-zinc-500 lg:col-span-1">
              <span className="mr-1">Works with</span>
              {["Zapier", "Make", "n8n", "any HTTPS endpoint"].map((t) => (
                <span key={t} className="rounded-full border border-zinc-200 bg-white px-2.5 py-0.5 font-medium text-zinc-700">
                  {t}
                </span>
              ))}
            </div>
          </div>

          <WebhooksCard webhooks={data.webhooks} events={data.events} onChange={refresh} />
          <ApiKeysCard keys={data.api_keys} onChange={refresh} />
          <ZapierCard />
        </div>
      )}
    </>
  );
}
