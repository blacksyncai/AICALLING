"use client";

import { PhoneIncoming } from "lucide-react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Card, CardHeader, Field, Select, Toggle } from "@/components/ui";
import { fetcher, put } from "@/lib/api";

interface CallbackSettings {
  enabled: boolean;
  window_days: 7 | 30 | 90;
  use_variables: boolean;
  use_summary: boolean;
  route_original: boolean;
  fallback_agent_id: string | null;
  crm_updates: boolean;
}

/** Smart Callback Recognition: people your campaigns called can call your numbers back. */
export function CallbackCard() {
  const toast = useToast();
  const { data, mutate } = useSWR<CallbackSettings>("/api/settings/callbacks", fetcher);
  const { data: agents } = useSWR<{ id: string; name: string }[]>("/api/agents/", fetcher);

  async function save(patch: Partial<CallbackSettings>) {
    if (!data) return;
    const next = { ...data, ...patch };
    await mutate(next, { revalidate: false });
    try {
      await mutate(await put<CallbackSettings>("/api/settings/callbacks", next), { revalidate: false });
    } catch (e) {
      toast((e as Error).message, "error");
      await mutate();
    }
  }

  if (!data) return null;
  return (
    <Card>
      <CardHeader
        title="Smart Callback Recognition"
        description="Automatically recognize prospects returning calls from your outbound campaigns and personalize conversations using their existing lead information."
        action={<PhoneIncoming className="h-5 w-5 text-zinc-400" />}
      />
      <div className="space-y-4 p-5">
        <Toggle
          checked={data.enabled}
          onChange={(v) => void save({ enabled: v })}
          label="Answer callbacks automatically"
          description="When someone calls back, your agent answers knowing who they are and why you called. Once they talk to you, your campaigns stop redialing them."
        />
        {data.enabled && (
          <>
            <Toggle checked={data.use_variables} onChange={(v) => void save({ use_variables: v })}
              label="Use the contact's campaign details" description="Their name and the columns from your list, like the property address." />
            <Toggle checked={data.use_summary} onChange={(v) => void save({ use_summary: v })}
              label="Pick up where you left off" description="If you spoke before, the agent gets a summary of that call." />
            <Toggle checked={data.route_original} onChange={(v) => void save({ route_original: v })}
              label="Answer with the agent that called them" description="Same voice, script and booking settings as the original call." />
            <Toggle checked={data.crm_updates} onChange={(v) => void save({ crm_updates: v })}
              label="Update your CRM after callbacks" description="Callback results sync like any other call." />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Recognize callbacks for">
                <Select value={String(data.window_days)} onChange={(e) => void save({ window_days: Number(e.target.value) as 7 | 30 | 90 })}>
                  <option value="7">7 days after a call</option>
                  <option value="30">30 days after a call</option>
                  <option value="90">90 days after a call</option>
                </Select>
              </Field>
              <Field label="Fallback agent" hint="Answers when the original agent can't, and unknown callers on your outbound numbers.">
                <Select value={data.fallback_agent_id ?? ""} onChange={(e) => void save({ fallback_agent_id: e.target.value || null })}>
                  <option value="">None</option>
                  {(agents ?? []).map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </Select>
              </Field>
            </div>
            <p className="text-xs text-zinc-500">
              A number with a live inbound campaign is always answered by that campaign&apos;s agent, which also gets the callback details.
            </p>
          </>
        )}
      </div>
    </Card>
  );
}
