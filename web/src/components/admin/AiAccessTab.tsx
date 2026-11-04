"use client";

import { Bot, Copy, ExternalLink } from "lucide-react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Notice, Spinner } from "@/components/ui";
import { del, fetcher } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface Conn {
  id: string;
  app: string;
  connected_at: string | null;
  last_used_at: string | null;
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

const APPS = [
  {
    name: "Claude",
    url: "https://claude.ai/settings/connectors",
    steps: [
      "Open Settings, Connectors and choose Add custom connector.",
      "Name it BlackSync Admin and paste the server URL below.",
      "Click Connect. Sign in to BlackSync with this login (unlock the admin portal first) and click Allow.",
    ],
  },
  {
    name: "ChatGPT",
    url: "https://chatgpt.com/#settings/Connectors",
    steps: [
      "Open Settings, Apps & Connectors and choose Create (turn on Developer mode under Advanced if asked).",
      "Name it BlackSync Admin, paste the server URL below and pick OAuth.",
      "Sign in to BlackSync with this login (unlock the admin portal first) and click Allow.",
    ],
  },
];

/** Admin → AI access: BlackSync Admin, the separate admin MCP server for ChatGPT and Claude. */
export function AiAccessTab() {
  const toast = useToast();
  const { data, error, mutate } = useSWR<{ server_url: string; connections: Conn[]; actions: Action[] }>(
    "/api/admin/ai-access",
    fetcher,
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(data?.server_url ?? "");
      toast("Server URL copied", "success");
    } catch {
      toast("Couldn't copy. Select the URL and copy it.", "error");
    }
  }

  async function disconnect(id: string) {
    try {
      await del(`/api/admin/ai-access/${id}`);
      await mutate();
      toast("Disconnected", "success");
    } catch (e) {
      toast((e as Error).message, "error");
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
          title="BlackSync Admin for ChatGPT and Claude"
          description="A separate connector from the customer one. It works in every customer account: create and edit agents, add contacts, update knowledge, run campaigns, CRM and Radar, and add credits. Only platform admins can connect it, and every action is logged below."
        />
        <div className="space-y-5 px-5 py-4">
          <div>
            <div className="mb-1.5 text-xs font-medium text-zinc-500">Server URL</div>
            <div className="flex gap-2">
              <code className="min-w-0 flex-1 truncate rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm">{data.server_url}</code>
              <Button size="sm" variant="secondary" onClick={() => void copy()}>
                <Copy className="h-4 w-4" /> Copy
              </Button>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {APPS.map((a) => (
              <div key={a.name} className="rounded-xl border border-zinc-200 p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-semibold text-zinc-900">{a.name}</span>
                  <a href={a.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-brand-600">
                    Open settings <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                </div>
                <ol className="list-decimal space-y-1 pl-4 text-xs leading-relaxed text-zinc-600">
                  {a.steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Connected" description="Your BlackSync Admin connections. Disconnect cuts access at once." />
        {data.connections.length === 0 ? (
          <p className="flex items-center gap-2 px-5 py-6 text-sm text-zinc-500">
            <Bot className="h-4 w-4" /> Not connected yet.
          </p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {data.connections.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-zinc-900">{c.app}</div>
                  <div className="mt-0.5 text-xs text-zinc-500">
                    Connected {c.connected_at ? timeAgo(c.connected_at) : "-"}
                    {c.last_used_at ? ` · last used ${timeAgo(c.last_used_at)}` : ""}
                    {c.account ? ` · working in ${c.account}` : ""}
                  </div>
                </div>
                <Button size="sm" variant="secondary" onClick={() => void disconnect(c.id)}>
                  Disconnect
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title="Admin action log" description="The latest 50 tool calls made through BlackSync Admin, newest first." />
        {data.actions.length === 0 ? (
          <p className="px-5 py-6 text-sm text-zinc-500">Nothing yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {data.actions.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-2.5 text-sm">
                <span className="w-24 shrink-0 text-xs text-zinc-500">{a.at ? timeAgo(a.at) : "-"}</span>
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
