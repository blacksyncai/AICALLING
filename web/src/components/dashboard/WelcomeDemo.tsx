"use client";

import { Headphones, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { WebCallPanel } from "@/components/agent/WebCallPanel";
import { VoiceCards } from "@/components/builder/VoiceCards";
import type { VoicesResponse } from "@/components/builder/StepPersonality";
import { useToast } from "@/components/toast";
import { Card } from "@/components/ui";
import { fetcher, patch } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Agent, SettingsStatus } from "@/lib/types";

const key = (orgId: string) => `blacksync:welcome-demo-hidden:${orgId}`;

/** First visit: pick a voice for Synchro (the welcome demo agent) and talk to it in the browser. */
// Zain (Version 1) right after the selected voice on the demo.
const DEMO_PINNED = ["95280ca0-610a-41c9-8457-1dcec809da61"];

export function WelcomeDemo() {
  const { session } = useSession();
  const toast = useToast();
  const orgId = session?.org?.id;
  const [hidden, setHidden] = useState<boolean | null>(null);
  useEffect(() => {
    if (!orgId) return;
    try {
      setHidden(window.localStorage.getItem(key(orgId)) === "1");
    } catch {
      setHidden(false);
    }
  }, [orgId]);

  const on = hidden === false;
  const { data: agents, mutate } = useSWR<Agent[]>(on ? "/api/agents/" : null, fetcher);
  const { data: tests } = useSWR<{ total: number }>(on ? "/api/calls/?call_type=web&page_size=1" : null, fetcher);
  const { data: voices } = useSWR<VoicesResponse>(on ? "/api/settings/voices" : null, fetcher, { revalidateOnFocus: false });
  const { data: status } = useSWR<SettingsStatus>(on ? "/api/settings/status" : null, fetcher);
  const demo = agents?.find((a) => a.template === "welcome_demo");
  const [voice, setVoice] = useState<string | null>(null);

  // Shown until they've tried a browser test (or hide it).
  if (!on || !demo || !tests || tests.total > 0) return null;

  async function pickVoice(id: string) {
    if (!demo) return;
    setVoice(id);
    try {
      await patch(`/api/agents/${demo.id}`, { voice_id: id });
      await mutate();
    } catch (e) {
      setVoice(null);
      toast((e as Error).message, "error");
    }
  }

  function hide() {
    try {
      if (orgId) window.localStorage.setItem(key(orgId), "1");
    } catch {
      /* storage blocked — hides for this visit */
    }
    setHidden(true);
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 px-5 pt-5">
        <span className="brand-gradient flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white shadow-sm">
          <Headphones className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-zinc-900">Meet {demo.name}, your demo agent</h2>
          <p className="mt-0.5 text-xs text-zinc-500">
            Pick a voice, then talk to {demo.name} right here in your browser — it&apos;s exactly what your callers will hear. Test calls are free.
          </p>
        </div>
        <button
          type="button"
          onClick={hide}
          className="-mr-1 -mt-1 rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
          aria-label="Hide the demo agent card"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <p className="mb-2 text-xs font-medium text-zinc-700">1. Choose her voice</p>
          <VoiceCards voices={voices} value={voice ?? demo.voice_id} language={demo.language || "en"} onChange={(id) => void pickVoice(id)} pinned={DEMO_PINNED} />
        </div>
        <div className="min-w-0">
          <p className="mb-2 text-xs font-medium text-zinc-700">2. Say hi</p>
          <WebCallPanel agentId={demo.id} enabled={!!status?.capabilities.web_call} variables={{}} beforeStart={async () => true} />
          <p className="mt-2 text-[11px] text-zinc-500">
            Want to change what she says? <Link href={`/agents/${demo.id}`} className="font-medium text-brand-700 hover:text-brand-800">Open her in the editor</Link>
          </p>
        </div>
      </div>
    </Card>
  );
}
