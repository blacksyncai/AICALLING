"use client";

import { Bot, Copy } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader } from "@/components/ui";
import { del, fetcher } from "@/lib/api";

interface Connections {
  server_url: string;
  connections: { id: string; app: string; account: string | null; connected_at: string | null; last_used_at: string | null }[];
}

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "never");

/** ChatGPT / Claude connector: the server URL to paste, and the assistants connected to this login. */
export function AssistantsCard() {
  const toast = useToast();
  const { data, mutate } = useSWR<Connections>("/api/oauth/connections", fetcher);

  async function disconnect(id: string) {
    try {
      await del(`/api/oauth/connections/${id}`);
      void mutate();
      toast("Disconnected", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <Card>
      <CardHeader
        title="ChatGPT & Claude"
        description="Work in BlackSync from your AI assistant: build agents, add contacts, run campaigns and review calls from a chat."
        action={
          <Link href="/connect/help" className="whitespace-nowrap text-sm font-medium text-brand-700 hover:underline">
            Setup guide
          </Link>
        }
      />
      <div className="space-y-4 px-5 pb-5">
        <div>
          <div className="mb-1 text-xs font-medium text-zinc-500">Server URL — add it as a connector in ChatGPT or Claude</div>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg bg-zinc-50 px-3 py-2 text-xs ring-1 ring-zinc-200">
              {data?.server_url ?? "https://blacksync.si/api/mcp"}
            </code>
            <Button
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(data?.server_url ?? "https://blacksync.si/api/mcp");
                toast("Copied", "success");
              }}
            >
              <Copy className="h-3.5 w-3.5" /> Copy
            </Button>
          </div>
        </div>
        {data && data.connections.length > 0 && (
          <div className="divide-y divide-zinc-100 rounded-xl ring-1 ring-zinc-200/80">
            {data.connections.map((c) => (
              <div key={c.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <Bot className="h-4 w-4 shrink-0 text-zinc-400" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-zinc-900">{c.app}</div>
                  <div className="truncate text-xs text-zinc-500">
                    {c.account ?? "No account picked"} · connected {day(c.connected_at)} · last used {day(c.last_used_at)}
                  </div>
                </div>
                <button type="button" onClick={() => void disconnect(c.id)} className="text-xs font-medium text-red-600 hover:underline">
                  Disconnect
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
