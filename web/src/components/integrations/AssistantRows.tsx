"use client";

import { Copy, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Modal } from "@/components/ui";
import { del, fetcher } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface Connections {
  server_url: string;
  connections: { id: string; app: string; account: string | null; connected_at: string | null; last_used_at: string | null }[];
}

const SERVER = "https://blacksync.si/api/mcp";

const APPS = [
  {
    key: "chatgpt",
    name: "ChatGPT",
    domain: "chatgpt.com",
    description: "Build agents, add contacts, run campaigns and review calls from a ChatGPT chat.",
    steps: [
      "In ChatGPT, open Settings → Apps & Connectors (turn on Developer mode under Advanced if asked).",
      "Choose Create, name it BlackSync, paste the server URL below and pick OAuth.",
      "Sign in to BlackSync when asked and click Allow.",
      "In a chat, pick BlackSync from the tools menu and ask, e.g. “What's my BlackSync setup status?”",
    ],
  },
  {
    key: "claude",
    name: "Claude",
    domain: "claude.ai",
    description: "Use BlackSync from Claude: set up your account, edit agents and read call results.",
    steps: [
      "In Claude, open Settings → Connectors and choose Add custom connector.",
      "Name it BlackSync and paste the server URL below.",
      "Click Connect, sign in to BlackSync and click Allow.",
      "Turn BlackSync on in a chat's tools menu and ask what you need.",
    ],
  },
] as const;

type App = (typeof APPS)[number];

function AppLogo({ domain }: { domain: string }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-white ring-1 ring-zinc-200/80">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`} alt="" className="h-6 w-6" />
    </span>
  );
}

/** ChatGPT and Claude in the integrations list: setup steps, the server URL and this login's connections. */
export function AssistantRows() {
  const toast = useToast();
  const { data, mutate } = useSWR<Connections>("/api/oauth/connections", fetcher);
  const [open, setOpen] = useState<App | null>(null);
  const url = data?.server_url ?? SERVER;
  const mine = (a: App) => (data?.connections ?? []).filter((c) => c.app.toLowerCase().includes(a.key));

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      toast("Server URL copied", "success");
    } catch {
      toast("Couldn't copy. Select the URL and copy it.", "error");
    }
  }

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
    <div>
      <div className="mb-2 px-1 text-xs font-medium uppercase tracking-wide text-zinc-500">AI assistants</div>
      <ul className="overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 [&>li+li]:border-t [&>li+li]:border-zinc-100">
        {APPS.map((a) => {
          const conns = mine(a);
          return (
            <li key={a.key}>
              <button
                type="button"
                onClick={() => setOpen(a)}
                className="group flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors hover:bg-zinc-50"
              >
                <AppLogo domain={a.domain} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="text-[15px] font-medium text-zinc-900">{a.name}</span>
                    {conns.length > 0 ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-1.5 py-px text-[10px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-1.5 py-px text-[10px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Live
                      </span>
                    )}
                  </span>
                  <span className="block truncate text-xs text-zinc-500">{a.description}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5 text-sm text-zinc-500 transition-colors group-hover:text-brand-600">
                  {conns.length ? "Manage" : "Set up"} <ExternalLink className="h-4 w-4" />
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <Modal open={!!open} onClose={() => setOpen(null)} title={open ? `Connect ${open.name}` : ""}>
        {open && (
          <div className="space-y-4 text-sm">
            <ol className="list-decimal space-y-1.5 pl-5 text-zinc-700">
              {open.steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
            <div>
              <div className="mb-1 text-xs font-medium text-zinc-500">Server URL</div>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 select-all truncate rounded-lg bg-zinc-50 px-3 py-2 text-xs ring-1 ring-zinc-200">{url}</code>
                <Button size="sm" onClick={() => void copy()}>
                  <Copy className="h-3.5 w-3.5" /> Copy
                </Button>
              </div>
            </div>
            {mine(open).length > 0 && (
              <div>
                <div className="mb-1 text-xs font-medium text-zinc-500">Connected to your login</div>
                <ul className="divide-y divide-zinc-100 rounded-xl ring-1 ring-zinc-200/80">
                  {mine(open).map((c) => (
                    <li key={c.id} className="flex items-center gap-3 px-3 py-2">
                      <span className="min-w-0 flex-1 truncate text-xs text-zinc-600">
                        {c.account ?? "No account picked"} · last used {c.last_used_at ? timeAgo(c.last_used_at) : "never"}
                      </span>
                      <button type="button" onClick={() => void disconnect(c.id)} className="text-xs font-medium text-red-600 hover:underline">
                        Disconnect
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-xs text-zinc-500">
              It acts as you, with your permissions, and asks before placing calls or starting campaigns.{" "}
              <Link href="/connect/help" className="font-medium text-brand-700 hover:underline">
                Full setup guide
              </Link>
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}
