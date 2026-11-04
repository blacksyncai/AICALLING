"use client";

import { Bot, ShieldCheck } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, Notice, Spinner } from "@/components/ui";
import { del, fetcher, post } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface Conn {
  id: string;
  app: string;
  connected_at: string | null;
  last_used_at: string | null;
  admin_until: string | null;
  account: string | null;
}
interface Action {
  id: string;
  at: string | null;
  account: string | null;
  tool: string;
  changed: boolean;
  ok: boolean;
  error: string | null;
}

const until = (iso: string) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** Admin → AI access: switch admin mode on for one ChatGPT/Claude connection, and see everything it did. */
export function AiAccessTab() {
  const toast = useToast();
  const { data, error, mutate } = useSWR<{ connections: Conn[]; actions: Action[] }>("/api/admin/ai-access", fetcher);
  const [busy, setBusy] = useState<string | null>(null);

  async function turnOn(id: string) {
    setBusy(id);
    try {
      await post(`/api/admin/ai-access/${id}`, { hours: 12 });
      await mutate();
      toast("Admin mode on for 12 hours. Refresh the connector in ChatGPT or Claude to see the admin tools.", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function turnOff(id: string) {
    setBusy(id);
    try {
      await del(`/api/admin/ai-access/${id}`);
      await mutate();
      toast("Admin mode off", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <Notice tone="red">Couldn&apos;t load AI access: {error.message}</Notice>;
  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="AI admin access"
          description="Lets one of your ChatGPT or Claude connections work inside any customer account: create and edit agents, add contacts, update knowledge, run campaigns and add credits. It turns itself off after 12 hours, and every action is logged below."
        />
        {data.connections.length === 0 ? (
          <EmptyState
            icon={<Bot className="h-5 w-5" />}
            title="No connections yet"
            description="Connect BlackSync in ChatGPT or Claude first (Integrations, AI assistants), signed in as you."
          />
        ) : (
          <ul className="divide-y divide-zinc-100">
            {data.connections.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-zinc-900">{c.app}</span>
                    {c.admin_until ? (
                      <Badge tone="amber">
                        <ShieldCheck className="h-3 w-3" /> Admin until {until(c.admin_until)}
                      </Badge>
                    ) : (
                      <Badge>Normal</Badge>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-zinc-500">
                    Connected {c.connected_at ? timeAgo(c.connected_at) : "—"}
                    {c.last_used_at ? ` · last used ${timeAgo(c.last_used_at)}` : ""}
                    {c.admin_until && c.account ? ` · working in ${c.account}` : ""}
                  </div>
                </div>
                {c.admin_until ? (
                  <Button size="sm" variant="secondary" disabled={busy === c.id} onClick={() => void turnOff(c.id)}>
                    Turn off
                  </Button>
                ) : (
                  <Button size="sm" variant="primary" disabled={busy === c.id} onClick={() => void turnOn(c.id)}>
                    Turn on admin mode
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title="Admin action log" description="The latest 50 tool calls made in admin mode, newest first." />
        {data.actions.length === 0 ? (
          <p className="px-5 py-6 text-sm text-zinc-500">Nothing yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {data.actions.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-2.5 text-sm">
                <span className="w-24 shrink-0 text-xs text-zinc-500">{a.at ? timeAgo(a.at) : "—"}</span>
                <span className="font-mono text-xs text-zinc-800">{a.tool}</span>
                {a.changed && <Badge tone="blue">Change</Badge>}
                {!a.ok && <Badge tone="red">Failed</Badge>}
                <span className="min-w-0 flex-1 truncate text-xs text-zinc-500">
                  {a.account ?? ""}
                  {a.error ? ` · ${a.error}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
