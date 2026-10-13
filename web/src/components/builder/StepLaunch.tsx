"use client";

import { ArrowUpRight, MessageSquare, Mic, Phone, Rocket } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import useSWR from "swr";
import { ChatPanel } from "@/components/agent/ChatPanel";
import { PhonePanel } from "@/components/agent/PhonePanel";
import { WebCallPanel } from "@/components/agent/WebCallPanel";
import { ImproveWithAI } from "@/components/agent-editor/ImproveWithAI";
import { CheckList, type Readiness } from "@/components/agent-editor/ReadinessCard";
import { useToast } from "@/components/toast";
import { Badge, Button, Notice, Spinner, Tabs } from "@/components/ui";
import { ApiError, fetcher, post } from "@/lib/api";
import type { BuilderCatalog, BusinessProfile } from "@/lib/builder";
import type { Agent, SettingsStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { LANGUAGES, type VoicesResponse } from "./StepPersonality";
import { displayHost } from "./parts";

type TestTab = "voice" | "chat" | "phone";

const DIRECTION: Record<string, string> = { outbound: "Calls out", inbound: "Answers calls", both: "Calls out and answers calls" };
const TEST_VARS = { name: "Jamie", company: "Globex" };

/** Step 5 — the agent exists (paused). Meet it, test it, refine it, then launch. */
export function StepLaunch({
  agentId,
  catalog,
  profile,
  voices,
  references,
}: {
  agentId: string;
  catalog: BuilderCatalog | undefined;
  profile: BusinessProfile | null;
  voices: VoicesResponse | undefined;
  references: number;
}) {
  const toast = useToast();
  const router = useRouter();
  const { data: agent, mutate, error } = useSWR<Agent>(`/api/agents/${agentId}`, fetcher, { revalidateOnFocus: false });
  const { data: status } = useSWR<SettingsStatus>("/api/settings/status", fetcher);
  const readinessUrl = `/api/agent-builder/agents/${agentId}/readiness`;
  const { data: readiness, mutate: refreshReadiness, isValidating } = useSWR<Readiness>(readinessUrl, fetcher, { shouldRetryOnError: false });
  const [tab, setTab] = useState<TestTab>("voice");
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState("");
  const caps = status?.capabilities;

  if (error) return <Notice tone="red">We couldn&apos;t load your agent: {(error as Error).message}</Notice>;
  if (!agent)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  const b = agent.builder ?? {};
  const live = agent.status === "active";
  const voice = [...(voices?.featured ?? []), ...(voices?.voices ?? [])].find((v) => v.id === agent.voice_id);
  const language = LANGUAGES.find(([k]) => k === agent.language)?.[1] ?? agent.language;
  const industry = catalog?.industries.find((i) => i.key === b.industry)?.label ?? b.industry;
  const objective = b.plan?.primary_objective;
  const knowledge = [
    profile && profile.item_count > 0 ? `${profile.item_count} facts${profile.website ? ` from ${displayHost(profile.website)}` : ""}` : null,
    references > 0 ? `${references} script${references === 1 ? "" : "s"} you added` : null,
  ].filter(Boolean);
  const actions = [
    agent.enable_booking ? "Books appointments" : null,
    agent.transfer_number ? `Transfers to ${agent.transfer_number}` : null,
    agent.ai_disclosure !== false ? "Says it's an AI" : null,
  ].filter(Boolean);
  const blockers = (readiness?.checks ?? []).filter((c) => c.status === "blocker");
  const toReview = (readiness?.checks ?? []).filter((c) => c.status !== "ok");

  async function launch() {
    setLaunching(true);
    setLaunchError("");
    try {
      await post(`/api/agent-builder/agents/${agentId}/launch`, {});
      await mutate();
      toast(`${agent!.name} is live`);
    } catch (e) {
      setLaunchError(e instanceof ApiError || e instanceof Error ? e.message : "Launch failed.");
      void refreshReadiness();
    } finally {
      setLaunching(false);
    }
  }

  return (
    <div>
      {/* Hero */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-medium text-brand-700">{live ? "Live" : "Ready to test"}</p>
          <h2 className="mt-1 font-display text-xl font-semibold tracking-tight text-zinc-900 sm:text-2xl">
            {live ? `${agent.name} is live` : `${agent.name} is ready to meet you`}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {agent.specialty && (
              <span className="max-w-[16rem] truncate rounded-md bg-zinc-900 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">
                {agent.specialty}
              </span>
            )}
            <Badge tone={live ? "green" : "gray"}>{live ? "Active" : "Paused until you launch"}</Badge>
          </div>
        </div>
        <Link href={`/agents/${agentId}`} className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-zinc-600 hover:text-zinc-900">
          Open full editor <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Starting point: set expectations and invite edits */}
      {!live && (
        <div className="mb-5 rounded-xl border border-brand-200 bg-brand-50/60 p-4">
          <p className="text-sm font-semibold text-zinc-900">This is your starting point</p>
          <p className="mt-1 text-sm text-zinc-700">
            Test {agent.name} a few times — most agents need a couple of tweaks before they sound just right. Change anything you like,
            and if you have a call script, objection answers or talking points you already use, paste them in with Improve with AI or add
            them in the full editor.
          </p>
          <Link
            href={`/agents/${agentId}`}
            className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800"
          >
            Open full editor <ArrowUpRight className="h-4 w-4" />
          </Link>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        {/* Summary */}
        <section className="rounded-xl border border-zinc-200 bg-white">
          <h3 className="border-b border-zinc-100 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">Summary</h3>
          <dl className="divide-y divide-zinc-50 px-4">
            <Row label="Voice" value={`${voice?.name ?? "Selected voice"}${language ? ` · ${language}` : ""}`} />
            <Row label="Industry" value={industry} />
            <Row label="Calls" value={b.direction ? DIRECTION[b.direction] : undefined} />
            <Row label="Mission" value={objective ? <span className="line-clamp-4">{objective}</span> : undefined} />
            <Row label="Knowledge" value={knowledge.length ? knowledge.join(" · ") : "None yet — add it anytime in Knowledge"} />
            <Row label="On the call" value={actions.join(" · ") || "Conversation only"} />
          </dl>
          <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 px-4 py-3">
            <ImproveWithAI
              agent={agent}
              beforeImprove={async () => true}
              onApplied={(updated) => {
                void mutate(updated, false);
                void refreshReadiness();
              }}
            />
            <Link
              href={`/agents/${agentId}`}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
            >
              Open full editor <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </section>

        {/* Test */}
        <section className="rounded-xl border border-zinc-200 bg-white p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-zinc-900">Talk to {agent.name}</h3>
          </div>
          <Tabs<TestTab>
            value={tab}
            onChange={setTab}
            tabs={[
              { value: "voice", label: "Voice", icon: <Mic className="h-3.5 w-3.5" /> },
              { value: "chat", label: "Chat", icon: <MessageSquare className="h-3.5 w-3.5" /> },
              { value: "phone", label: "Phone", icon: <Phone className="h-3.5 w-3.5" /> },
            ]}
          />
          <div className="mt-3 min-h-[280px]">
            {tab === "voice" && <WebCallPanel agentId={agentId} enabled={!!caps?.web_call} variables={TEST_VARS} beforeStart={async () => true} />}
            {tab === "chat" && (
              <ChatPanel
                key={agent.first_message}
                agentId={agentId}
                firstMessage={agent.first_message}
                enabled={!!caps?.chat_test}
                variables={TEST_VARS}
                beforeStart={async () => true}
              />
            )}
            {tab === "phone" && <PhonePanel agentId={agentId} enabled={!!caps?.phone_call} beforeStart={async () => true} />}
          </div>
        </section>
      </div>

      {/* Launch */}
      <section
        className={cn(
          "mt-5 rounded-xl border p-4",
          live ? "border-emerald-200 bg-emerald-50/60" : blockers.length ? "border-zinc-200 bg-white" : "border-brand-200 bg-brand-50/50",
        )}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-zinc-900">
              {live ? "Launched" : !readiness ? "Checking what's needed to go live…" : blockers.length ? `${blockers.length} thing${blockers.length === 1 ? "" : "s"} to fix before launch` : "Ready to launch"}
            </h3>
            <p className="mt-0.5 text-xs text-zinc-600">
              {live
                ? "Your agent can take calls and run in campaigns. Pause it anytime from the agent editor."
                : "Your agent stays paused until you launch it. Test it as much as you like first."}
            </p>
          </div>
          {!live && (
            <Button variant="primary" onClick={launch} loading={launching} disabled={!readiness || blockers.length > 0 || isValidating}>
              {!launching && <Rocket className="h-4 w-4" />} Launch agent
            </Button>
          )}
          {live && (
            <Link href="/campaigns">
              <Button variant="secondary">Start a campaign</Button>
            </Link>
          )}
        </div>
        {launchError && (
          <div className="mt-3">
            <Notice tone="red">{launchError}</Notice>
          </div>
        )}
        {!live && toReview.length > 0 && (
          <div className="mt-3 rounded-lg border border-zinc-200 bg-white px-3">
            <CheckList checks={toReview} onSection={() => router.push(`/agents/${agentId}`)} />
          </div>
        )}
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode | undefined }) {
  return (
    <div className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-4">
      <dt className="shrink-0 text-xs text-zinc-500 sm:w-24 sm:pt-0.5">{label}</dt>
      <dd className={cn("min-w-0 break-words text-sm", value ? "text-zinc-900" : "text-zinc-400")}>{value || "Not set"}</dd>
    </div>
  );
}
