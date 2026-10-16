"use client";
import Link from "next/link";
import {
  CrmCommandCard,
  TOOL_NAMES,
  toolName,
  type CrmCommand,
} from "./CrmAssistantCommands";
import { RadarSourcePicker, type RadarSource } from "./RadarSourcePicker";
import { FollowUpBossTools } from "./FollowUpBossTools";
import AiMascotInput from "@/components/ui/ai-mascot-input";
import { useState, useEffect } from "react";
import useSWR from "swr";
import {
  ArrowDown,
  Database,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  FolderPlus,
  Layers,
  MessageSquare,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Send,
  Settings2,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  Notice,
  Select,
  Spinner,
  Textarea,
} from "@/components/ui";
import { fetcher, patch, post, put } from "@/lib/api";
import { humanize, timeAgo } from "@/lib/utils";
import {
  blankRule,
  destinations,
  OUTCOMES,
  VERIFICATION_LABELS,
  type Action,
  type Overview,
  type Preview,
  type Resources,
  type Rule,
} from "./automation-types";
import styles from "./radar-automations.module.css";
const BASE = "/api/radar/automations";
const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong";
type ResourceRequest = { kind: string; name: string };

export function RadarAutomations() {
  const { data, error, mutate } = useSWR<Overview>(BASE, fetcher);
  const { data: commandHistory, mutate: refreshCommands } = useSWR<{
    items: CrmCommand[];
  }>(`${BASE}/commands`, fetcher);
  const [commands, setCommands] = useState<CrmCommand[]>([]);
  const [reviewRequest, setReviewRequest] = useState({ id: "", token: 0 });
  const [picked, setPicked] = useState("");
  const [view, setView] = useState("build");
  const [request, setRequest] = useState("");
  const [messages, setMessages] = useState<
    { role: string; text: string; provider: string }[]
  >([]);
  const [drafts, setDrafts] = useState<(Rule & { key: string })[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [suggestions, setSuggestions] = useState<ResourceRequest[]>([]);
  const provider =
    picked ||
    data?.connections.find((c) => c.provider === "followupboss")?.provider ||
    data?.connections[0]?.provider ||
    "";
  const {
    data: resources,
    error: resourceError,
    mutate: refreshResources,
  } = useSWR<Resources>(
    provider ? `${BASE}/resources/${provider}` : null,
    fetcher,
  );
  type Conversation = {
    id: string;
    title: string;
    drafts?: Rule[];
    selected_source?: RadarSource | null;
    messages: { role: string; text: string }[];
  };
  const [conversationIds, setConversationIds] = useState<
    Record<string, string>
  >({});
  const [newChatProviders, setNewChatProviders] = useState<
    Record<string, boolean>
  >({});
  const {
    data: conversations,
    mutate: refreshConversations,
    error: conversationError,
    isLoading: conversationsLoading,
  } = useSWR<{
    items: Conversation[];
  }>(provider ? `${BASE}/conversations/${provider}` : null, fetcher);
  const [sourcePickerOpen, setSourcePickerOpen] = useState(false);
  const [continueAfterSource, setContinueAfterSource] = useState(false);
  const [selectedSources, setSelectedSources] = useState<
    Record<string, RadarSource | undefined>
  >({});
  const selectedSource = selectedSources[provider];
  const openConversation = (chat: Conversation) => {
    setSelectedSources((old) => ({
      ...old,
      [provider]: chat.selected_source || undefined,
    }));
    setConversationIds((old) => ({ ...old, [provider]: chat.id }));
    setNewChatProviders((old) => ({ ...old, [provider]: false }));
    setMessages((old) => [
      ...old.filter((m) => m.provider !== provider),
      ...chat.messages.map((m) => ({ ...m, provider })),
    ]);
    setDrafts(
      (chat.drafts || []).map((r) => ({
        ...r,
        key: crypto.randomUUID(),
        dirty: true,
        status: "draft",
      })),
    );
    setSuggestions([]);
    setRequest("");
  };
  useEffect(() => {
    if (
      !provider ||
      newChatProviders[provider] ||
      conversationIds[provider] ||
      !conversations?.items.length
    )
      return;
    const chat = conversations.items[0];
    setSelectedSources((old) => ({
      ...old,
      [provider]: chat.selected_source || undefined,
    }));
    setDrafts(
      (chat.drafts || []).map((r) => ({
        ...r,
        key: crypto.randomUUID(),
        dirty: true,
        status: "draft",
      })),
    );
    setConversationIds((old) => ({ ...old, [provider]: chat.id }));
    setMessages((old) => [
      ...old.filter((m) => m.provider !== provider),
      ...chat.messages.map((m) => ({ ...m, provider })),
    ]);
  }, [provider, conversations, conversationIds, newChatProviders]);
  const sourceLabel = selectedSource
    ? [
        selectedSource.agent_id
          ? data?.agents.find((a) => a.id === selectedSource.agent_id)?.name ||
            "Selected agent"
          : "",
        selectedSource.campaign_id
          ? data?.campaigns.find((c) => c.id === selectedSource.campaign_id)
              ?.name || "Selected campaign"
          : "",
        selectedSource.blacksync_pond_id
          ? resources?.blacksync_ponds.find(
              (p) => p.id === selectedSource.blacksync_pond_id,
            )?.name || "BlackSync pond"
          : "",
        selectedSource.pond_id
          ? resources?.crm_ponds.find((p) => p.id === selectedSource.pond_id)
              ?.name || "CRM pond"
          : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  const connection = data?.connections.find((c) => c.provider === provider);
  const edit = (r: Rule) => {
    setPicked(r.provider);
    setDrafts((old) => [
      { ...structuredClone(r), key: crypto.randomUUID(), dirty: false },
      ...old,
    ]);
    setView("build");
  };
  const prepareFubTool = async (spec: Record<string, unknown>) => {
    let command = await post<CrmCommand>(`${BASE}/commands`, {
      provider: "followupboss",
      spec,
    });
    if (!command.writes) {
      command = await post<CrmCommand>(
        `${BASE}/commands/${command.id}/execute`,
        { confirmed: true },
      );
      if (command.status !== "succeeded")
        throw new Error(command.error || "Could not read Follow Up Boss.");
    }
    setCommands((old) => [command, ...old.filter((c) => c.id !== command.id)]);
    if (command.writes) {
      setReviewRequest({ id: command.id, token: Date.now() });
      setView("build");
    }
    await refreshCommands();
    if (!command.writes) setView("commands");
  };
  const ask = async (
    sourceOverride?: RadarSource,
    messageOverride?: string,
  ) => {
    const text = (messageOverride || request).trim();
    if (!text || !provider || busy) return;
    setBusy(true);
    setErr("");
    setMessages((m) => [...m, { role: "user", text, provider }]);
    setRequest("");
    try {
      const result = await post<{
        message: string;
        conversation_id?: string;
        needs_source?: boolean;
        commands?: CrmCommand[];
        drafts: Rule[];
        resource_requests: ResourceRequest[];
      }>(`${BASE}/draft`, {
        provider,
        message: text,
        selected_source: sourceOverride || selectedSource || null,
        conversation_id: conversationIds[provider] || null,
        history: messages
          .filter((m) => m.provider === provider)
          .slice(-12)
          .map((m) => ({ role: m.role, text: m.text.slice(0, 4000) })),
      });
      if (result.conversation_id) {
        setConversationIds((old) => ({
          ...old,
          [provider]: result.conversation_id!,
        }));
        setNewChatProviders((old) => ({ ...old, [provider]: false }));
      }
      void refreshConversations();
      setMessages((m) => [
        ...m,
        { role: "assistant", text: result.message, provider },
      ]);
      setDrafts((old) => [
        ...result.drafts.map((r) => ({
          ...r,
          key: crypto.randomUUID(),
          dirty: true,
          status: "draft" as const,
        })),
        ...old.filter(
          (previous) =>
            !result.drafts.some(
              (next) =>
                next.provider === previous.provider &&
                ((next.id && next.id === previous.id) ||
                  next.name === previous.name),
            ),
        ),
      ]);
      const incoming = result.commands ?? [];
      setCommands((old) => [
        ...incoming,
        ...old.filter((c) => !incoming.some((next) => next.id === c.id)),
      ]);
      const review = incoming.find((c) => c.writes && c.status === "draft");
      if (review) setReviewRequest({ id: review.id, token: Date.now() });
      void refreshCommands();
      setSuggestions(result.resource_requests);
      if (result.needs_source) {
        setContinueAfterSource(true);
        setSourcePickerOpen(true);
      }
    } catch (e) {
      setRequest(text);
      setErr(errorText(e));
      if (
        /unknown (?:source agent|campaign)|choose (?:the campaign|it explicitly|a source)/i.test(
          errorText(e),
        )
      ) {
        setContinueAfterSource(true);
        setSourcePickerOpen(true);
      }
    } finally {
      setBusy(false);
    }
  };
  if (error) return <Notice tone="red">{errorText(error)}</Notice>;
  if (!data)
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  if (!data.connections.length)
    return (
      <Card className="p-6">
        <h2 className="text-lg font-semibold">
          Connect a CRM to build automations
        </h2>
        <p className="mt-2 text-sm text-zinc-500">
          Start with Follow Up Boss, or use your other connected CRM’s supported
          actions.
        </p>
        <Link
          className="mt-4 inline-block text-sm font-semibold text-brand-600"
          href="/integrations"
        >
          Connect a CRM →
        </Link>
      </Card>
    );
  return (
    <div className={styles.root}>
      <div className={styles.topbar}>
        <div>
          <span className={styles.eyebrow}>RADAR AUTOMATIONS</span>
          <h2>From a conversation to the next step.</h2>
          <p>Describe the workflow. Review the rule. Decide when it runs.</p>
        </div>
        <label className={styles.crmSelect}>
          Connected CRM
          <Select
            aria-label="Automation CRM"
            value={provider}
            onChange={(e) => {
              setPicked(e.target.value);
              setSuggestions([]);
              setErr("");
            }}
          >
            {data.connections.map((c) => (
              <option key={c.provider} value={c.provider}>
                {c.name}
                {c.label ? ` · ${c.label}` : ""}
              </option>
            ))}
          </Select>
        </label>
      </div>
      <nav className={styles.views} aria-label="Automation sections">
        {[
          { key: "build", label: "Build automation", icon: Sparkles },
          {
            key: "rules",
            label: `Saved rules (${data.rules.length})`,
            icon: Workflow,
          },
          {
            key: "resources",
            label:
              provider === "followupboss"
                ? "Deal boards & ponds"
                : "Ponds & stages",
            icon: Layers,
          },
          { key: "activity", label: "Activity", icon: Clock3 },
          { key: "commands", label: "CRM actions", icon: Database },
        ].map(({ key, label, icon: Icon }) => (
          <button
            type="button"
            key={key}
            aria-current={view === key ? "page" : undefined}
            onClick={() => setView(key)}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </nav>
      {resourceError && <Notice tone="red">{errorText(resourceError)}</Notice>}
      {resources?.warnings.map((w) => (
        <Notice tone="amber" key={w}>
          {w}
        </Notice>
      ))}
      {view === "build" && (
        <>
          {provider === "followupboss" && (
            <FollowUpBossTools onPrepare={prepareFubTool} />
          )}
          <div className={styles.buildGrid}>
            <Card className={styles.chat}>
              <div className={styles.chatHeading}>
                <span className={styles.botIcon}>
                  <Bot size={22} />
                </span>
                <div>
                  <h3>What should Radar do?</h3>
                  <p>Build around your team’s workflow.</p>
                </div>
                <Badge tone="gray">Draft mode</Badge>
              </div>
              {conversationError && (
                <Notice tone="red">
                  Saved conversations could not be loaded.{" "}
                  <button
                    type="button"
                    onClick={() => void refreshConversations()}
                  >
                    Retry
                  </button>
                </Notice>
              )}
              <div className="flex flex-wrap items-center gap-2 border-b border-zinc-100 p-4">
                <Select
                  aria-label="Saved Radar conversations"
                  disabled={busy}
                  value={conversationIds[provider] || ""}
                  onChange={(e) => {
                    const chat = conversations?.items.find(
                      (c) => c.id === e.target.value,
                    );
                    if (chat) openConversation(chat);
                  }}
                  className="min-w-0 flex-1"
                >
                  <option value="">New conversation</option>
                  {conversations?.items.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
                </Select>
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setConversationIds((old) => ({ ...old, [provider]: "" }));
                    setSelectedSources((old) => ({
                      ...old,
                      [provider]: undefined,
                    }));
                    setNewChatProviders((old) => ({
                      ...old,
                      [provider]: true,
                    }));
                    setMessages((old) =>
                      old.filter((m) => m.provider !== provider),
                    );
                    setDrafts([]);
                    setSuggestions([]);
                    setRequest("");
                  }}
                >
                  New chat
                </Button>
                <p className="w-full text-xs text-zinc-500">
                  Conversations are saved privately to your workspace and
                  connected CRM. Saved rules remain in Saved rules.
                </p>
              </div>
              <div
                className={styles.messages}
                aria-live="polite"
                style={{
                  display: messages.some((m) => m.provider === provider)
                    ? undefined
                    : "none",
                }}
              >
                {messages
                  .filter((m) => m.provider === provider)
                  .map((m, i) => (
                    <div
                      className={
                        m.role === "user"
                          ? styles.userMessage
                          : styles.assistantMessage
                      }
                      key={i}
                    >
                      <span>{m.role === "user" ? "You" : "Radar"}</span>
                      <p>{m.text}</p>
                    </div>
                  ))}
                {busy && (
                  <p className="flex items-center gap-2 text-sm text-zinc-500">
                    <Spinner />
                    Drafting a workflow…
                  </p>
                )}
              </div>
              <div className="p-4 sm:p-5">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setContinueAfterSource(false);
                      setSourcePickerOpen(true);
                    }}
                  >
                    <Bot size={15} />
                    {selectedSource
                      ? "Change call source"
                      : "Choose call source"}
                  </Button>
                  {sourceLabel && (
                    <span className="min-w-0 break-words text-xs text-zinc-500">
                      {sourceLabel}
                    </span>
                  )}
                </div>
                <RadarSourcePicker
                  open={sourcePickerOpen}
                  onClose={() => setSourcePickerOpen(false)}
                  selected={selectedSource}
                  overview={data}
                  resources={resources}
                  continueDrafting={continueAfterSource}
                  onSelect={(source) => {
                    setSelectedSources((old) => ({
                      ...old,
                      [provider]: source,
                    }));
                    setSourcePickerOpen(false);
                    setErr("");
                    if (continueAfterSource)
                      void ask(
                        source,
                        request.trim() ||
                          "Use the selected source to continue drafting the automation rules we discussed.",
                      );
                  }}
                />
                <AiMascotInput
                  title="What can Radar do for you?"
                  subtitle="Work with your CRM, or build a reusable automation."
                  value={request}
                  onChange={setRequest}
                  onSubmit={() => ask()}
                  isProcessing={busy}
                  disabled={!provider || conversationsLoading}
                  showWelcome={!messages.some((m) => m.provider === provider)}
                  placeholder={`Tell Radar what to do in ${connection?.name ?? "your CRM"}…`}
                />
              </div>
              <div className="px-4 pb-3">
                <Button
                  onClick={() => {
                    setDrafts((d) => [
                      { ...blankRule(provider), key: crypto.randomUUID() },
                      ...d,
                    ]);
                  }}
                >
                  <Plus size={14} />
                  Build manually
                </Button>
              </div>
              {err && (
                <div className="px-4 pb-4">
                  <Notice tone="red">{err}</Notice>
                </div>
              )}
            </Card>
            <aside className={styles.guide}>
              <span className={styles.eyebrow}>AVAILABLE CRM TOOLS</span>
              <p className="text-xs leading-6 text-zinc-500">
                Actions depend on this CRM’s API and your connected account’s
                permissions. Ask in chat, then review the proposed action.
              </p>
              <ul className="space-y-2 text-xs">
                {resources?.assistant_tools?.map((tool) => (
                  <li
                    key={tool.action}
                    className="flex items-center justify-between gap-3"
                  >
                    <span>{toolName(tool.action, provider)}</span>
                    <Badge tone="gray">
                      {tool.writes ? "Review first" : "Read only"}
                    </Badge>
                  </li>
                ))}
              </ul>
              <span className={styles.eyebrow}>AUTOMATION WORKFLOWS</span>
              <div>
                <span>01</span>
                <h3>Choose the source</h3>
                <p>An agent, campaign or Follow Up Boss pond.</p>
              </div>
              <div>
                <span>02</span>
                <h3>Define the evidence</h3>
                <p>
                  A clear name confirmation, a named voicemail, an outcome or an
                  extracted answer.
                </p>
              </div>
              <div>
                <span>03</span>
                <h3>Choose the destination</h3>
                <p>
                  Use a BlackSync pond, a CRM pond or a supported stage. Add a
                  tag when available.
                </p>
              </div>
            </aside>
          </div>
          {suggestions.length > 0 && (
            <Card className="mt-4 p-4">
              <h3 className="text-sm font-semibold">Suggested resources</h3>
              <p className="mt-1 text-xs text-zinc-500">
                These haven’t been created. Open Ponds & stages to create them
                explicitly.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {suggestions.map((s, i) => (
                  <button
                    className={styles.resourceSuggestion}
                    key={i}
                    onClick={() => setView("resources")}
                    type="button"
                  >
                    <FolderPlus size={14} />
                    {s.name}
                    <ArrowRight size={13} />
                  </button>
                ))}
              </div>
            </Card>
          )}
          <div className="mt-5 space-y-4">
            {commands
              .filter((c) => c.provider === provider)
              .map((c) => (
                <CrmCommandCard
                  key={c.id}
                  command={c}
                  reviewRequest={
                    reviewRequest.id === c.id ? reviewRequest.token : 0
                  }
                  onReviewOpened={() => setReviewRequest({ id: "", token: 0 })}
                  onUpdated={(next) => {
                    setCommands((old) =>
                      old.map((x) => (x.id === next.id ? next : x)),
                    );
                    void refreshCommands();
                    void refreshResources();
                    if (next.status === "succeeded") {
                      const pipe = next.result.pipeline as
                        | { name: string; stages: { label: string }[] }
                        | undefined;
                      const receipt = pipe
                        ? `${pipe.name} is ready${next.provider === "followupboss" ? " in Follow Up Boss → Deals / Deal Tracking" : ""}. Stages: ${pipe.stages.map((s) => s.label).join(", ")}.`
                        : String(
                            next.result.message ??
                              `${TOOL_NAMES[next.spec.action] ?? "CRM action"} completed.`,
                          );
                      setMessages((old) => [
                        ...old,
                        {
                          role: "assistant",
                          provider: next.provider,
                          text: receipt,
                        },
                      ]);
                    }
                  }}
                />
              ))}
          </div>
          <div className={styles.drafts}>
            {drafts
              .filter((d) => d.provider === provider)
              .map((d) => (
                <DraftEditor
                  key={d.key}
                  draft={d}
                  resources={resources}
                  overview={data}
                  onChange={(next) =>
                    setDrafts((all) =>
                      all.map((x) =>
                        x.key === d.key ? { ...next, key: d.key } : x,
                      ),
                    )
                  }
                  onSaved={() => void mutate()}
                  onResources={() => setView("resources")}
                  onRemove={() =>
                    setDrafts((all) => all.filter((x) => x.key !== d.key))
                  }
                />
              ))}
          </div>
        </>
      )}
      {view === "commands" && (
        <div className="space-y-4">
          <details className="rounded-xl border border-zinc-200 bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold">
              Available actions for {connection?.name}
            </summary>
            <ul className="mt-4 space-y-2 text-xs">
              {resources?.assistant_tools?.map((t) => (
                <li key={t.action}>
                  {toolName(t.action, provider)} ·{" "}
                  {t.writes ? "Review required" : "Read only"}
                </li>
              ))}
            </ul>
          </details>
          <p className="text-xs leading-6 text-zinc-500">
            One-time CRM requests from chat. Proposals expire after 30 minutes.
            Completed results remain here for review.
          </p>
          {commandHistory?.items
            .filter((c) => c.provider === provider)
            .map((c) => (
              <CrmCommandCard
                key={`${c.id}-${c.status}`}
                command={c}
                onUpdated={() => void refreshCommands()}
              />
            ))}
          {!commandHistory?.items.some((c) => c.provider === provider) && (
            <Card className="p-6 text-sm text-zinc-500">
              No CRM actions yet. Ask the assistant to find a contact or create
              a pipeline.
            </Card>
          )}
        </div>
      )}
      {view === "rules" && (
        <div className={styles.savedRules}>
          {data.rules.length === 0 ? (
            <Card className="p-6">
              <h3 className="font-semibold">
                Your first automation starts with a request.
              </h3>
              <p className="mt-2 text-sm text-zinc-500">
                Create a draft, choose a destination and activate it when ready.
              </p>
              <Button className="mt-4" onClick={() => setView("build")}>
                Build automation
              </Button>
            </Card>
          ) : (
            data.rules.map((r) => (
              <Card key={r.id} className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="font-semibold">{r.name}</h3>
                    <p className="mt-1 text-xs text-zinc-500">
                      {data.connections.find((c) => c.provider === r.provider)
                        ?.name ?? r.provider}{" "}
                      · Version {r.version}
                    </p>
                  </div>
                  <Badge tone={r.status === "active" ? "green" : "gray"}>
                    {r.status}
                  </Badge>
                </div>
                <p className="mt-4 text-sm text-zinc-600">
                  {r.spec.condition.kind === "verification"
                    ? VERIFICATION_LABELS[r.spec.condition.value]
                    : humanize(r.spec.condition.value)}{" "}
                  → {r.spec.actions.length} action
                  {r.spec.actions.length === 1 ? "" : "s"}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button onClick={() => edit(r)}>
                    <Settings2 size={14} />
                    Review / edit
                  </Button>
                  <StateButton rule={r} onUpdate={() => void mutate()} />
                </div>
              </Card>
            ))
          )}
        </div>
      )}
      {view === "resources" &&
        (resources ? (
          <ResourceManager
            key={provider}
            provider={provider}
            resources={resources}
            suggestions={suggestions}
            refresh={() => void refreshResources()}
          />
        ) : (
          !resourceError && <Spinner />
        ))}
      {view === "activity" && <AutomationActivity />}
    </div>
  );
}

function StateButton({ rule, onUpdate }: { rule: Rule; onUpdate: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <>
      <Button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await patch(`${BASE}/${rule.id}/state`, {
              status: rule.status === "active" ? "paused" : "active",
            });
            onUpdate();
          } catch (e) {
            setError(errorText(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {rule.status === "active" ? <Pause size={14} /> : <Play size={14} />}{" "}
        {rule.status === "active" ? "Pause" : "Activate"}
      </Button>
      {error && (
        <p className="text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function DraftEditor({
  draft,
  resources,
  overview,
  onChange,
  onSaved,
  onResources,
  onRemove,
}: {
  draft: Rule;
  resources?: Resources;
  overview: Overview;
  onChange: (r: Rule) => void;
  onSaved: () => void;
  onResources: () => void;
  onRemove: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState("");
  const options = resources ? destinations(resources) : [];
  const update = (next: Rule) => {
    onChange({ ...next, dirty: true });
    setPreview(null);
    setSelected(new Set());
    setNotice("");
  };
  const changeSource = (patch: Partial<Rule["spec"]["source"]>) =>
    update({
      ...draft,
      spec: { ...draft.spec, source: { ...draft.spec.source, ...patch } },
    });
  const changeCondition = (patch: Partial<Rule["spec"]["condition"]>) =>
    update({
      ...draft,
      spec: { ...draft.spec, condition: { ...draft.spec.condition, ...patch } },
    });
  const setActions = (actions: Action[]) =>
    update({ ...draft, spec: { ...draft.spec, actions } });
  const payload = () => ({
    name: draft.name,
    provider: draft.provider,
    request: draft.request,
    spec: draft.spec,
  });
  const doAction = async (kind: string) => {
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      if (kind === "save") {
        const saved = draft.id
          ? await put<Rule>(`${BASE}/${draft.id}`, payload())
          : await post<Rule>(BASE, payload());
        onChange({ ...saved, dirty: false });
        onSaved();
        setNotice("Saved as a draft. Activate it to process new calls.");
      }
      if (kind === "preview") {
        setPreview(await post<Preview>(`${BASE}/preview`, payload()));
        setSelected(new Set());
      }
      if (kind === "run") {
        const result = await post<{ queued: number }>(
          `${BASE}/${draft.id}/run`,
          { call_ids: [...selected] },
        );
        setNotice(
          `${result.queued} matching call(s) queued for routing. No phone calls are placed.`,
        );
        setSelected(new Set());
      }
      if (kind === "state") {
        const saved = await patch<Rule>(`${BASE}/${draft.id}/state`, {
          status: draft.status === "active" ? "paused" : "active",
        });
        onChange({ ...saved, dirty: false });
        onSaved();
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  };
  const valid =
    !!draft.name.trim() &&
    draft.spec.actions.length > 0 &&
    draft.spec.actions.every((a) => !!a.target_id);
  return (
    <Card className={styles.editor}>
      <div className={styles.editorHeading}>
        <div>
          <span className={styles.eyebrow}>REVIEW YOUR AUTOMATION</span>
          <h3>{draft.id ? "Saved workflow" : "Workflow draft"}</h3>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            tone={draft.status === "active" && !draft.dirty ? "green" : "gray"}
          >
            {draft.dirty ? "Unsaved draft" : (draft.status ?? "draft")}
          </Badge>
          <button
            type="button"
            aria-label="Close workflow draft"
            onClick={onRemove}
          >
            <X size={17} />
          </button>
        </div>
      </div>
      <div className={styles.editorBody}>
        <Field label="Automation name">
          <Input
            aria-label="Automation name"
            value={draft.name}
            maxLength={120}
            onChange={(e) => update({ ...draft, name: e.target.value })}
          />
        </Field>
        <div className={styles.ruleSection}>
          <span className={styles.stepNumber}>01</span>
          <div className="min-w-0 flex-1">
            <h4>When a phone call finishes</h4>
            <p>
              Only calls started after activation run automatically. Browser
              tests are excluded.
            </p>
            <div className={styles.fields}>
              <Field label="Agent">
                <Select
                  aria-label="Source agent"
                  value={draft.spec.source.agent_id ?? ""}
                  onChange={(e) =>
                    changeSource({ agent_id: e.target.value || null })
                  }
                >
                  <option value="">All agents</option>
                  {overview.agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Campaign">
                <Select
                  aria-label="Source campaign"
                  value={draft.spec.source.campaign_id ?? ""}
                  onChange={(e) =>
                    changeSource({ campaign_id: e.target.value || null })
                  }
                >
                  <option value="">All campaigns</option>
                  {overview.campaigns.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              {!!resources?.blacksync_ponds.length && (
                <Field label="Source BlackSync pond">
                  <Select
                    aria-label="Source BlackSync pond"
                    value={draft.spec.source.blacksync_pond_id || ""}
                    onChange={(e) =>
                      changeSource({
                        blacksync_pond_id: e.target.value || null,
                      })
                    }
                  >
                    <option value="">Any BlackSync pond</option>
                    {resources.blacksync_ponds.map((pond) => (
                      <option key={pond.id} value={pond.id}>
                        {pond.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              {draft.provider === "followupboss" && (
                <Field label="Follow Up Boss lead source (optional)">
                  <Input
                    aria-label="Source lead source"
                    value={draft.spec.source.lead_source || ""}
                    maxLength={120}
                    placeholder="For example: BlackSync AI"
                    onChange={(e) =>
                      changeSource({ lead_source: e.target.value })
                    }
                  />
                  <p className="text-xs text-zinc-500">
                    Matches the linked contact’s existing source. Leave blank
                    for any source; this does not create Lead Flow.
                  </p>
                </Field>
              )}
              {resources?.capabilities.route_pond && (
                <Field label="Source CRM pond">
                  <Select
                    aria-label="Source CRM pond"
                    value={draft.spec.source.pond_id}
                    onChange={(e) => changeSource({ pond_id: e.target.value })}
                  >
                    <option value="">Any pond</option>
                    {resources.crm_ponds.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
          </div>
        </div>
        <div className={styles.ruleSection}>
          <span className={styles.stepNumber}>02</span>
          <div className="min-w-0 flex-1">
            <h4>If the evidence matches</h4>
            <div className={styles.fields}>
              <Field label="Condition type">
                <Select
                  aria-label="Condition type"
                  value={draft.spec.condition.kind}
                  onChange={(e) =>
                    changeCondition({
                      kind: e.target.value as
                        "verification" | "outcome" | "field",
                      value:
                        e.target.value === "verification"
                          ? "name_confirmed"
                          : e.target.value === "outcome"
                            ? "interested"
                            : "",
                      field: e.target.value === "field" ? "timeline" : "",
                      operator: "equals",
                    })
                  }
                >
                  <option value="verification">
                    Name / number verification
                  </option>
                  <option value="outcome">Call outcome</option>
                  <option value="field">Extracted answer</option>
                </Select>
              </Field>
              {draft.spec.condition.kind === "verification" ? (
                <Field label="Verification result">
                  <Select
                    aria-label="Verification result"
                    value={draft.spec.condition.value}
                    onChange={(e) => changeCondition({ value: e.target.value })}
                  >
                    {Object.entries(VERIFICATION_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : draft.spec.condition.kind === "outcome" ? (
                <Field label="Call outcome">
                  <Select
                    aria-label="Call outcome"
                    value={draft.spec.condition.value}
                    onChange={(e) => changeCondition({ value: e.target.value })}
                  >
                    {OUTCOMES.map((o) => (
                      <option key={o} value={o}>
                        {humanize(o)}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : (
                <>
                  <Field label="Extracted field">
                    <Input
                      aria-label="Extracted field"
                      placeholder="timeline"
                      value={draft.spec.condition.field}
                      onChange={(e) =>
                        changeCondition({ field: e.target.value })
                      }
                    />
                  </Field>
                  <Field label="Comparison">
                    <Select
                      aria-label="Field comparison"
                      value={draft.spec.condition.operator}
                      onChange={(e) =>
                        changeCondition({
                          operator: e.target.value as
                            "equals" | "contains" | "exists",
                        })
                      }
                    >
                      <option value="equals">Equals</option>
                      <option value="contains">Contains</option>
                      <option value="exists">Has a value</option>
                    </Select>
                  </Field>
                  {draft.spec.condition.operator !== "exists" && (
                    <Field label="Value">
                      <Input
                        aria-label="Condition value"
                        value={draft.spec.condition.value}
                        onChange={(e) =>
                          changeCondition({ value: e.target.value })
                        }
                      />
                    </Field>
                  )}
                </>
              )}
            </div>
            <p>
              Name confirmation requires a clear name check and reply. A named
              voicemail is a separate result; a connected call alone is not
              confirmation.
            </p>
          </div>
        </div>
        <div className={styles.ruleSection}>
          <span className={styles.stepNumber}>03</span>
          <div className="min-w-0 flex-1">
            <h4>Then take these actions</h4>
            {draft.spec.actions.some((a) => a.kind === "crm_deal_stage") && (
              <Notice tone="amber">
                This routes a linked contact into a deal on the selected board,
                creating a deal if needed. It preserves later or closed stages
                and stops for review when multiple deals match. Contact stages
                and ponds are separate.
              </Notice>
            )}
            {draft.requested_destination && !draft.spec.actions.length && (
              <p>Choose or create “{draft.requested_destination}”.</p>
            )}
            {draft.spec.actions.map((a, i) => (
              <div className={styles.actionRow} key={i}>
                {a.kind === "crm_tag" ? (
                  <Input
                    aria-label={`Tag for action ${i + 1}`}
                    value={a.target_id}
                    placeholder="Tag name"
                    onChange={(e) =>
                      setActions(
                        draft.spec.actions.map((x, j) =>
                          i === j ? { ...x, target_id: e.target.value } : x,
                        ),
                      )
                    }
                  />
                ) : (
                  <Select
                    aria-label={`Destination for action ${i + 1}`}
                    value={JSON.stringify(a)}
                    onChange={(e) =>
                      setActions(
                        draft.spec.actions.map((x, j) =>
                          i === j ? (JSON.parse(e.target.value) as Action) : x,
                        ),
                      )
                    }
                  >
                    <option value={JSON.stringify(a)} disabled>
                      {options.find(
                        (o) => JSON.stringify(o.action) === JSON.stringify(a),
                      )?.label ?? "Choose destination"}
                    </option>
                    {options.map((o) => (
                      <option
                        key={JSON.stringify(o.action)}
                        value={JSON.stringify(o.action)}
                      >
                        {o.label}
                      </option>
                    ))}
                  </Select>
                )}
                <button
                  type="button"
                  aria-label={`Remove action ${i + 1}`}
                  onClick={() =>
                    setActions(draft.spec.actions.filter((_, j) => i !== j))
                  }
                >
                  <X size={16} />
                </button>
              </div>
            ))}
            {draft.spec.actions.length < 4 && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Select
                  aria-label="Add routing action"
                  value=""
                  className="min-w-0 flex-1"
                  onChange={(e) => {
                    if (e.target.value)
                      setActions([
                        ...draft.spec.actions,
                        JSON.parse(e.target.value) as Action,
                      ]);
                  }}
                >
                  <option value="">+ Choose a destination</option>
                  {options.map((o) => (
                    <option
                      key={JSON.stringify(o.action)}
                      value={JSON.stringify(o.action)}
                    >
                      {o.label}
                    </option>
                  ))}
                </Select>
                {resources?.capabilities.tag && (
                  <Button
                    onClick={() =>
                      setActions([
                        ...draft.spec.actions,
                        { kind: "crm_tag", target_id: "", pipeline_id: "" },
                      ])
                    }
                  >
                    + Add tag
                  </Button>
                )}
              </div>
            )}
            <button
              type="button"
              className="mt-3 text-xs font-semibold text-brand-600"
              onClick={onResources}
            >
              Create a pond, stage or pipeline →
            </button>
            <p>
              Do-not-call contacts are excluded. Routing never launches another
              call.
            </p>
          </div>
        </div>
        {error && <Notice tone="red">{error}</Notice>}
        {notice && <Notice tone="green">{notice}</Notice>}
        <div className={styles.editorActions}>
          <Button
            loading={busy === "preview"}
            disabled={!valid || !!busy}
            onClick={() => void doAction("preview")}
          >
            <CheckCircle2 size={15} />
            Preview matches
          </Button>
          <Button
            variant="primary"
            loading={busy === "save"}
            disabled={!valid || !!busy}
            onClick={() => void doAction("save")}
          >
            Save draft
          </Button>
          {draft.id && !draft.dirty && (
            <Button disabled={!!busy} onClick={() => void doAction("state")}>
              {draft.status === "active" ? (
                <Pause size={14} />
              ) : (
                <Play size={14} />
              )}{" "}
              {draft.status === "active" ? "Pause" : "Activate"}
            </Button>
          )}
        </div>
        {preview && (
          <div className={styles.preview}>
            {preview.contact_resolution && (
              <Notice tone="amber">
                Before routing, Radar looks for an existing Follow Up Boss
                person and saves the link.{" "}
                {preview.create_missing_contacts
                  ? "If none exists, your integration setting allows creating a contact with source BlackSync AI."
                  : "Creating missing contacts is off. Enable it in Integrations → Follow Up Boss if needed; existing matches can still be linked."}{" "}
                This preview creates no contacts.
              </Notice>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h4>
                  {preview.matched} match{preview.matched === 1 ? "" : "es"} in{" "}
                  {preview.checked} recent calls
                </h4>
                <p>
                  Read-only preview, up to {preview.limit} calls. No changes
                  have been applied.
                </p>
              </div>
              <Button
                size="sm"
                onClick={() =>
                  setSelected(
                    new Set(
                      preview.items
                        .filter((i) => i.matches)
                        .map((i) => i.call_id),
                    ),
                  )
                }
              >
                Select matches
              </Button>
            </div>
            {!preview.items.length && (
              <p className="mt-4 text-sm text-zinc-500">
                No completed calls in this source yet.
              </p>
            )}
            <div className={styles.previewList}>
              {preview.items.map((item) => (
                <div className={styles.previewItem} key={item.call_id}>
                  <input
                    aria-label={`Select call for ${item.name}`}
                    type="checkbox"
                    disabled={!item.matches}
                    checked={selected.has(item.call_id)}
                    onChange={(e) =>
                      setSelected((old) => {
                        const next = new Set(old);
                        if (e.target.checked) next.add(item.call_id);
                        else next.delete(item.call_id);
                        return next;
                      })
                    }
                  />
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <strong>{item.name}</strong>
                      <Badge tone={item.matches ? "green" : "gray"}>
                        {VERIFICATION_LABELS[item.status] ??
                          humanize(item.status)}
                      </Badge>
                    </div>
                    <p>
                      {item.phone} · {item.reason}
                    </p>
                    {item.evidence.map((e, i) => (
                      <blockquote key={i}>
                        <span>{e.role === "user" ? "Contact" : "Agent"}</span> “
                        {e.text}”
                      </blockquote>
                    ))}
                    <Link
                      href={`/calls/${item.call_id}`}
                      className="text-xs font-semibold text-brand-600"
                    >
                      View call →
                    </Link>
                  </div>
                </div>
              ))}
            </div>
            <Button
              disabled={
                !selected.size ||
                !draft.id ||
                draft.dirty ||
                draft.status !== "active" ||
                !!busy
              }
              loading={busy === "run"}
              onClick={() => void doAction("run")}
            >
              Apply to {selected.size} selected past call
              {selected.size === 1 ? "" : "s"}
            </Button>
            <p>
              To apply past matches, save and activate this exact rule first.
              New calls run automatically after activation.
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}

function ResourceManager({
  provider,
  resources,
  suggestions,
  refresh,
}: {
  provider: string;
  resources: Resources;
  suggestions: ResourceRequest[];
  refresh: () => void;
}) {
  const [kind, setKind] = useState("blacksync_pond");
  const [name, setName] = useState("");
  const [stageNames, setStageNames] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pond, setPond] = useState("");
  const { data: members, error: memberError } = useSWR<{
    name: string;
    members: {
      lead_id: string;
      name: string;
      phone: string;
      call_id: string;
    }[];
  }>(pond ? `${BASE}/ponds/${pond}/members` : null, fetcher);
  const available = [
    { key: "blacksync_pond", label: "BlackSync pond" },
    ...(resources.capabilities.create_pond
      ? [{ key: "crm_pond", label: `${resources.provider_name} pond` }]
      : []),
    ...(resources.capabilities.create_stage
      ? [{ key: "crm_stage", label: `${resources.provider_name} lead stage` }]
      : []),
    ...(resources.capabilities.create_pipeline
      ? [
          {
            key: "crm_pipeline",
            label:
              provider === "followupboss"
                ? "Follow Up Boss deal board (Deals)"
                : `${resources.provider_name} deal pipeline`,
          },
        ]
      : []),
  ];
  return (
    <div className={styles.resourceGrid}>
      <Card className="p-5">
        <span className={styles.eyebrow}>CREATE A DESTINATION</span>
        <h3 className="mt-2 text-lg font-semibold">
          Give the next step a home.
        </h3>
        <p className="mt-2 text-sm leading-6 text-zinc-500">
          BlackSync ponds stay in this workspace. CRM resources are created in
          the connected account using its permissions.
        </p>
        <form
          className="mt-5 space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            setNotice("");
            try {
              const result = await post<{ name: string; location: string }>(
                `${BASE}/resources/${provider}`,
                {
                  kind,
                  name,
                  ...(kind === "crm_pipeline"
                    ? {
                        stages: stageNames
                          .split("\n")
                          .map((x) => x.trim())
                          .filter(Boolean)
                          .map((label) => ({ label, kind: "active" })),
                      }
                    : {}),
                },
              );
              setNotice(`“${result.name}” is ready in ${result.location}.`);
              setName("");
              refresh();
            } catch (err) {
              setError(errorText(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Create in">
            <Select
              aria-label="Resource type"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {available.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Name">
            <Input
              aria-label="New resource name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              placeholder="Verified Contacts"
              required
            />
          </Field>
          {kind === "crm_pipeline" && (
            <Field label="Stages (one per line)">
              <Textarea
                aria-label="Pipeline stages"
                rows={4}
                required
                value={stageNames}
                onChange={(e) => setStageNames(e.target.value)}
                placeholder={"New\nIn progress"}
              />
              <p className="mt-1 text-xs text-zinc-500">
                These stages are active. Ask the assistant to include won/lost
                stages or add stages to an existing pipeline.
              </p>
            </Field>
          )}
          {kind === "crm_pipeline" && (
            <Notice tone="amber">
              This creates a CRM deal pipeline. It is separate from lead-stage
              routing and does not move contacts into a deal.
            </Notice>
          )}
          <Button
            type="submit"
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
          >
            <Plus size={15} />
            Create resource
          </Button>
        </form>
        {suggestions.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {suggestions.map((s, i) => (
              <button
                type="button"
                className={styles.resourceSuggestion}
                key={i}
                onClick={() => {
                  setName(s.name);
                  if (available.some((x) => x.key === s.kind)) setKind(s.kind);
                }}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}
        {error && (
          <div className="mt-4">
            <Notice tone="red">{error}</Notice>
          </div>
        )}
        {notice && (
          <div className="mt-4">
            <Notice tone="green">{notice}</Notice>
          </div>
        )}
      </Card>
      <div className="space-y-4">
        <Card className="p-5">
          <div className="flex justify-between gap-3">
            <h3 className="font-semibold">BlackSync ponds</h3>
            <button
              aria-label="Refresh resources"
              onClick={refresh}
              type="button"
            >
              <RefreshCw size={15} />
            </button>
          </div>
          {!resources.blacksync_ponds.length && (
            <p className="mt-3 text-sm text-zinc-500">
              Create a pond to organize confirmed contacts and review queues.
            </p>
          )}
          {resources.blacksync_ponds.map((p) => (
            <button
              type="button"
              className={styles.pondRow}
              key={p.id}
              onClick={() => setPond(p.id)}
            >
              <span>
                <Layers size={16} />
                {p.name}
              </span>
              <span>
                {p.members ?? 0} contacts <ArrowRight size={14} />
              </span>
            </button>
          ))}
        </Card>
        <Card className="p-5">
          <h3 className="font-semibold">
            {resources.provider_name} destinations
          </h3>
          {resources.crm_ponds.map((p) => (
            <div className={styles.pondRow} key={p.id}>
              <span>{p.name}</span>
              <Badge tone="gray">CRM pond</Badge>
            </div>
          ))}
          {resources.pipelines.map((p) => (
            <div key={p.id} className="mt-4">
              <h4 className="text-xs font-semibold text-zinc-500">{p.name}</h4>
              <div className="mt-2 flex flex-wrap gap-2">
                {p.stages.map((s) => (
                  <Badge key={s.id} tone="gray">
                    {s.label}
                  </Badge>
                ))}
              </div>
            </div>
          ))}
          {resources.deal_pipelines.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold text-zinc-500">
                Deal pipelines
              </h4>
              <div className="mt-2 flex flex-wrap gap-2">
                {resources.deal_pipelines.map((p) => (
                  <Badge key={p.id} tone="gray">
                    {p.name}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          <p className="mt-4 text-xs leading-5 text-zinc-500">
            Only supported actions are offered. The CRM may require admin
            permissions for resource creation.
          </p>
        </Card>
      </div>
      <Modal
        open={!!pond}
        onClose={() => setPond("")}
        title={members?.name ?? "Pond contacts"}
        wide
      >
        {memberError ? (
          <Notice tone="red">{errorText(memberError)}</Notice>
        ) : !members ? (
          <Spinner />
        ) : !members.members.length ? (
          <p className="text-sm text-zinc-500">
            No contacts have been routed here yet.
          </p>
        ) : (
          members.members.map((m) => (
            <div className={styles.pondRow} key={`${m.lead_id}-${m.phone}`}>
              <span>
                {m.name} · {m.phone}
              </span>
              <Link href={`/calls/${m.call_id}`} className="text-brand-600">
                View call →
              </Link>
            </div>
          ))
        )}
      </Modal>
    </div>
  );
}

function AutomationActivity() {
  const { data, error, mutate } = useSWR<{
    items: {
      id: string;
      rule_name: string;
      call_id: string;
      status: string;
      attempts: number;
      error: string;
      result: {
        reason?: string;
        contact?: { id: string; status: string; name?: string };
        csv_data?: {
          synced: string[];
          unchanged: string[];
          conflicts: string[];
          unmapped: string[];
          created_fields: string[];
          warnings: string[];
          snapshot: boolean;
        };
        actions?: Record<
          string,
          | string
          | {
              id?: string;
              stage_id?: string;
              unchanged?: boolean;
              reason?: string;
            }
        >;
      };
      created_at: string;
      next_at?: string | null;
    }[];
  }>(`${BASE}/activity`, fetcher, { refreshInterval: 10000 });
  const [retryErr, setRetryErr] = useState("");
  if (error) return <Notice tone="red">{errorText(error)}</Notice>;
  if (!data) return <Spinner />;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h3 className="font-semibold">Automation activity</h3>
          <p className="mt-1 text-xs text-zinc-500">
            Completed actions, retries and skipped contacts. Updates every 10
            seconds.
          </p>
        </div>
        <Button size="sm" onClick={() => void mutate()}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>
      {retryErr && (
        <div className="mt-4">
          <Notice tone="red">{retryErr}</Notice>
        </div>
      )}
      {!data.items.length && (
        <div className={styles.activityEmpty}>
          <Workflow size={30} />
          <h4>No executions yet</h4>
          <p>
            Activate a saved rule to process new calls, or preview and
            explicitly apply it to selected past calls.
          </p>
        </div>
      )}
      {data.items.map((i) => (
        <div className={styles.activityRow} key={i.id}>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <strong>{i.rule_name}</strong>
              <Badge
                tone={
                  i.status === "succeeded"
                    ? "green"
                    : i.status === "failed"
                      ? "red"
                      : "gray"
                }
              >
                {humanize(i.status)}
              </Badge>
            </div>
            <p>
              {timeAgo(i.created_at)} · {i.attempts} attempt
              {i.attempts === 1 ? "" : "s"}
            </p>
            {i.result.reason && <p>{i.result.reason}</p>}
            {i.result.contact && (
              <p className="text-emerald-700">
                Follow Up Boss contact {i.result.contact.id}:{" "}
                {i.result.contact.status === "created_or_deduplicated"
                  ? "created or matched by FUB"
                  : i.result.contact.status === "linked_existing"
                    ? "found and linked"
                    : "link confirmed"}
              </p>
            )}
            {Object.entries(i.result.actions ?? {}).map(([k, v]) => (
              <p key={k} className="flex items-center gap-1">
                <CheckCircle2 size={12} />
                {typeof v === "string"
                  ? v
                  : `Deal ${v.id || ""} · ${v.reason || (v.unchanged ? "already at or beyond this stage" : `stage ${v.stage_id || "confirmed"}`)}`}
              </p>
            ))}
            {i.result.csv_data && (
              <div className="my-2 rounded-xl bg-zinc-50 p-3 text-xs leading-6">
                <p>
                  CSV data: {i.result.csv_data.synced.length} fields filled ·{" "}
                  {i.result.csv_data.created_fields.length} custom fields
                  created.
                </p>
                {i.result.csv_data.snapshot && (
                  <p>
                    Full source data preserved in the FUB contact background.
                  </p>
                )}
                {!!i.result.csv_data.conflicts.length && (
                  <p className="text-amber-700">
                    Existing FUB values preserved:{" "}
                    {i.result.csv_data.conflicts.join(", ")}
                  </p>
                )}
                {!!i.result.csv_data.unmapped.length && (
                  <p className="text-amber-700">
                    Retained in the CSV snapshot:{" "}
                    {i.result.csv_data.unmapped.join(", ")}
                  </p>
                )}
                {i.result.csv_data.warnings.map((warning, index) => (
                  <p key={index} className="text-amber-700">
                    {warning}
                  </p>
                ))}
              </div>
            )}
            {i.error && <p className="text-red-600">{i.error}</p>}
            {i.next_at && (
              <p>Retry scheduled: {new Date(i.next_at).toLocaleString()}</p>
            )}
            <Link
              href={`/calls/${i.call_id}`}
              className="text-xs font-semibold text-brand-600"
            >
              View call →
            </Link>
          </div>
          {i.status === "succeeded" && i.result.contact && (
            <Button
              size="sm"
              onClick={async () => {
                setRetryErr("");
                try {
                  await post(`${BASE}/activity/${i.id}/sync-data`);
                  void mutate();
                } catch (e) {
                  setRetryErr(errorText(e));
                }
              }}
            >
              Sync CSV data
            </Button>
          )}
          {["retry", "failed"].includes(i.status) && (
            <Button
              size="sm"
              onClick={async () => {
                setRetryErr("");
                try {
                  await post(`${BASE}/activity/${i.id}/retry`);
                  void mutate();
                } catch (e) {
                  setRetryErr(errorText(e));
                }
              }}
            >
              Retry
            </Button>
          )}
        </div>
      ))}
    </Card>
  );
}
