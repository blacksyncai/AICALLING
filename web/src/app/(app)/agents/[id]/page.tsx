"use client";

import { ArrowLeft, ArrowUpRight, BookOpen, Brain, Check, Eye, MessageSquare, Mic, Phone, Plus, Sparkles, Trash2, Upload, Wrench, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { ChatPanel } from "@/components/agent/ChatPanel";
import { PhonePanel } from "@/components/agent/PhonePanel";
import { VoiceModelSettings } from "@/components/agent/VoiceModelSettings";
import { WebCallPanel } from "@/components/agent/WebCallPanel";
import { CreatedBanner } from "@/components/agent-editor/CreatedBanner";
import { ImproveWithAI } from "@/components/agent-editor/ImproveWithAI";
import { assemblePrompt, humanizeKey } from "@/components/agent-editor/prompt";
import { CheckList, ReadinessCard, type Readiness } from "@/components/agent-editor/ReadinessCard";
import { QualityPanel } from "@/components/agent-editor/QualityPanel";
import { SectionsEditor } from "@/components/agent-editor/SectionsEditor";
import { VersionHistory } from "@/components/agent-editor/VersionHistory";
import { sectionOrder } from "@/lib/builder";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, Field, Input, Modal, Notice, Spinner, Tabs, Textarea, Toggle } from "@/components/ui";
import { fetcher, patch } from "@/lib/api";
import type { Agent, SettingsStatus, Voice } from "@/lib/types";
import { cn } from "@/lib/utils";

type Section = "prompt" | "knowledge" | "voice" | "actions" | "analysis";
type TestTab = "voice" | "chat" | "phone";

const SECTIONS: { value: Section; label: string; icon: typeof Brain }[] = [
  { value: "prompt", label: "Prompt", icon: Brain },
  { value: "knowledge", label: "Knowledge", icon: BookOpen },
  { value: "voice", label: "Voice & Model", icon: Mic },
  { value: "actions", label: "Actions", icon: Zap },
  { value: "analysis", label: "Post-call analysis", icon: Sparkles },
];

const VARIABLES = ["name", "full_name", "company", "email", "phone", "role"];

const EDITABLE: (keyof Agent)[] = [
  "name", "description", "status", "system_prompt", "first_message", "knowledge_base", "language",
  "llm_model", "temperature", "voice_id", "voice_speed", "background_audio", "enable_booking",
  "calcom_event_type_id", "transfer_number", "max_duration_seconds", "extraction_fields", "success_criteria",
  "ai_disclosure", "builder",
];

function pickEditable(a: Agent) {
  return Object.fromEntries(EDITABLE.map((k) => [k, a[k]])) as Partial<Agent>;
}

/** PATCH body: editable fields, leaving out builder fields the backend didn't send. */
function patchBody(a: Agent) {
  return Object.fromEntries(Object.entries(pickEditable(a)).filter(([k, v]) => v !== undefined && !(k === "builder" && v === null)));
}

const squash = (s: string) => s.replace(/\s+/g, " ").trim();

// Readiness "fix" anchors (#voice, #booking …) → editor tab.
const HASH_SECTION: Record<string, Section> = {
  prompt: "prompt", script: "prompt", first_message: "prompt", system_prompt: "prompt",
  knowledge: "knowledge", knowledge_base: "knowledge",
  voice: "voice", model: "voice",
  actions: "actions", booking: "actions", transfer: "actions", disclosure: "actions", ai_disclosure: "actions",
  analysis: "analysis",
};

export default function AgentEditorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const toast = useToast();
  const { data: saved, mutate, error } = useSWR<Agent>(`/api/agents/${id}`, fetcher, { revalidateOnFocus: false });
  const { data: status } = useSWR<SettingsStatus>("/api/settings/status", fetcher);
  const { data: voices } = useSWR<{ source: string; voices: Voice[]; featured?: Voice[] }>("/api/settings/voices", fetcher, { revalidateOnFocus: false });

  const [draft, setDraft] = useState<Agent | null>(null);
  const [section, setSection] = useState<Section>("prompt");
  const [testTab, setTestTab] = useState<TestTab>("chat");
  const [saving, setSaving] = useState(false);
  const [testVars, setTestVars] = useState<Record<string, string>>({ name: "Jamie", company: "Globex" });
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const readinessUrl = `/api/agent-builder/agents/${id}/readiness`;
  const {
    data: readiness,
    error: readinessError,
    isValidating: readinessLoading,
    mutate: refreshReadiness,
  } = useSWR<Readiness>(readinessUrl, fetcher, { revalidateOnFocus: true, shouldRetryOnError: false });
  const [justCreated, setJustCreated] = useState(false);
  const [blockersOpen, setBlockersOpen] = useState(false);
  const [rawPrompt, setRawPrompt] = useState(false);
  const [openReadiness, setOpenReadiness] = useState(0);
  const testPanelRef = useRef<HTMLDivElement>(null);
  const readinessRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);

  // `?created=1` — arriving from the AI builder. Show the banner once, then drop the param.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("created") === "1") {
      setJustCreated(true);
      router.replace(`/agents/${id}`, { scroll: false });
    }
  }, [id, router]);

  useEffect(() => {
    if (saved && !draft) setDraft(saved);
  }, [saved, draft]);

  useEffect(() => {
    if (status?.capabilities.web_call) setTestTab((t) => (t === "chat" ? "voice" : t));
  }, [status?.capabilities.web_call]);

  const dirty = useMemo(
    () => !!saved && !!draft && JSON.stringify(pickEditable(saved)) !== JSON.stringify(pickEditable(draft)),
    [saved, draft],
  );

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const set = <K extends keyof Agent>(key: K, value: Agent[K]) => setDraft((d) => (d ? { ...d, [key]: value } : d));

  const save = useCallback(async (): Promise<boolean> => {
    if (!draft) return false;
    setSaving(true);
    try {
      const updated = await patch<Agent>(`/api/agents/${id}`, patchBody(draft));
      await mutate(updated, false);
      setDraft(updated);
      refreshReadiness();
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    } finally {
      setSaving(false);
    }
  }, [draft, id, mutate, toast, refreshReadiness]);

  // Tests always run against the saved config, so save pending edits first.
  const beforeTest = useCallback(async () => (dirty ? save() : true), [dirty, save]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (dirty) save().then((ok) => ok && toast("Agent saved"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, save, toast]);

  if (error) return <Notice tone="red">{error.message}</Notice>;
  if (!draft)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );

  function insertVariable(v: string) {
    const el = promptRef.current;
    const token = `{{${v}}}`;
    if (!el || !draft) return set("system_prompt", `${draft?.system_prompt ?? ""}${token}`);
    const { selectionStart: s, selectionEnd: e } = el;
    set("system_prompt", draft.system_prompt.slice(0, s) + token + draft.system_prompt.slice(e));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(s + token.length, s + token.length);
    });
  }

  async function onKbFile(file: File) {
    if (file.size > 2_000_000) return toast("File too large (max 2 MB of text)", "error");
    const text = await file.text();
    set("knowledge_base", `${draft!.knowledge_base ? `${draft!.knowledge_base}\n\n` : ""}## ${file.name}\n${text}`);
    toast(`Added ${file.name} to knowledge`);
  }

  const caps = status?.capabilities;
  const builder = draft.builder ?? null;
  const builderSections = builder?.sections && Object.keys(builder.sections).length > 0 ? builder.sections : null;
  const useSections = !!builderSections && !rawPrompt;
  const order = sectionOrder(builder);
  const promptOutOfSync = !!builderSections && !!saved && squash(assemblePrompt(builderSections, order)) !== squash(draft.system_prompt);
  const blockers = readiness?.checks.filter((c) => c.status === "blocker") ?? [];
  const chips = builder ? [builder.industry, builder.use_case, builder.direction].filter(Boolean).map((k) => humanizeKey(k)) : [];

  function setSectionText(key: string, text: string) {
    setDraft((d) => {
      if (!d?.builder) return d;
      const sections = { ...(d.builder.sections ?? {}), [key]: text };
      return { ...d, builder: { ...d.builder, sections }, system_prompt: assemblePrompt(sections, sectionOrder(d.builder)) };
    });
  }

  function goToSection(hash: string) {
    const target = HASH_SECTION[hash];
    if (!target) return;
    setSection(target);
    setBlockersOpen(false);
    requestAnimationFrame(() => editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  function toggleStatus() {
    if (!draft) return;
    if (draft.status !== "active" && blockers.length > 0) {
      setBlockersOpen(true);
      return;
    }
    set("status", draft.status === "active" ? "paused" : "active");
  }

  function scrollToTest() {
    const el = testPanelRef.current;
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.focus({ preventScroll: true });
  }

  function scrollToReadiness() {
    setOpenReadiness((n) => n + 1);
    readinessRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    readinessRef.current?.focus({ preventScroll: true });
  }

  return (
    <div className="-mx-4 -my-6 sm:-mx-8 sm:-my-8">
      {/* Header */}
      <div className="sticky top-14 z-20 flex flex-wrap items-center gap-3 border-b border-zinc-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-8 lg:top-0">
        <Link href="/agents" className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100" aria-label="Back to agents">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <input
          value={draft.name}
          onChange={(e) => set("name", e.target.value)}
          className="min-w-0 flex-1 rounded-md bg-transparent px-1 text-lg font-semibold focus:bg-zinc-50 focus:outline-none"
          aria-label="Agent name"
        />
        <button
          onClick={toggleStatus}
          title="Paused agents can still be tested, but campaigns shouldn't use them"
          aria-label={`Status: ${draft.status === "active" ? "Active" : "Paused"}. Click to ${draft.status === "active" ? "pause" : "activate"}.`}
        >
          <Badge tone={draft.status === "active" ? "green" : "gray"}>{draft.status === "active" ? "Active" : "Paused"}</Badge>
        </button>
        <Button variant="primary" onClick={() => save().then((ok) => ok && toast("Agent saved"))} loading={saving} disabled={!dirty}>
          {!saving && <Check className="h-4 w-4" />}
          {dirty ? "Save changes" : "Saved"}
        </Button>
      </div>

      <div className="grid gap-6 px-4 py-6 sm:px-8 xl:grid-cols-[minmax(0,1fr)_400px]">
        {/* Editor */}
        <div className="min-w-0 space-y-4">
          {justCreated && (
            <CreatedBanner
              onTest={scrollToTest}
              onReview={() => goToSection("prompt")}
              onReadiness={scrollToReadiness}
              onDismiss={() => setJustCreated(false)}
            />
          )}
          {chips.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Built with AI">
              <span className="inline-flex items-center gap-1 font-medium text-brand-700">
                <Sparkles className="h-3.5 w-3.5" /> Built with AI
              </span>
              {chips.map((c, i) => (
                <span key={i} className="rounded-md bg-zinc-100 px-2 py-0.5 font-medium text-zinc-600">
                  {c}
                </span>
              ))}
            </div>
          )}
          <ReadinessCard
            ref={readinessRef}
            data={readiness}
            error={readinessError}
            loading={readinessLoading}
            onRefresh={() => refreshReadiness()}
            onSection={goToSection}
            forceOpen={openReadiness}
          />
          <div ref={editorRef} className="scroll-mt-32">
          <div className="scroll-thin mb-5 flex gap-1 overflow-x-auto border-b border-zinc-200">
            {SECTIONS.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                onClick={() => setSection(value)}
                className={cn(
                  "-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium",
                  section === value ? "border-brand-600 text-brand-700" : "border-transparent text-zinc-500 hover:text-zinc-800",
                )}
              >
                <Icon className="h-4 w-4" /> {label}
              </button>
            ))}
          </div>

          {section === "prompt" && (
            <div className="space-y-5">
              <Field label="Description" hint="Internal note — not used by the agent.">
                <Input value={draft.description} onChange={(e) => set("description", e.target.value)} />
              </Field>
              <Field label="First message" hint="Spoken word-for-word as soon as the call connects. Leave empty to let the agent improvise.">
                <Textarea rows={2} value={draft.first_message} onChange={(e) => set("first_message", e.target.value)} />
              </Field>
              <div className="flex flex-wrap items-center gap-2">
                <ImproveWithAI
                  agent={saved ?? draft}
                  beforeImprove={beforeTest}
                  onApplied={(updated) => {
                    mutate(updated, false);
                    setDraft(updated);
                    refreshReadiness();
                  }}
                />
                <VersionHistory
                  agent={saved ?? draft}
                  dirty={dirty}
                  onRestored={(updated) => {
                    mutate(updated, false);
                    setDraft(updated);
                    refreshReadiness();
                  }}
                />
                {builderSections && (
                  <button
                    onClick={() => setRawPrompt((v) => !v)}
                    className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800"
                  >
                    <Eye className="h-3.5 w-3.5" /> {rawPrompt ? "Edit by section" : "View full prompt"}
                  </button>
                )}
              </div>
              {useSections && promptOutOfSync && (
                <Notice tone="amber">
                  The full prompt was edited directly and no longer matches these sections. Saving from the section editor will rebuild it from
                  the sections below.{" "}
                  <button className="font-medium underline" onClick={() => setRawPrompt(true)}>
                    Edit the full prompt instead
                  </button>
                </Notice>
              )}
              {useSections && builderSections ? (
                <div>
                  {builder?.quality && <QualityPanel quality={builder.quality} />}
                  <SectionsEditor agentId={id} sections={builderSections} order={order} onChange={setSectionText} />
                  <p className="mt-1.5 text-xs text-zinc-500">
                    Use lead variables like <code>{"{{name}}"}</code> or <code>{"{{company}}"}</code> anywhere — they&apos;re filled from each lead.{" "}
                    {draft.system_prompt.length.toLocaleString()} chars
                  </p>
                </div>
              ) : (
              <div>
                {builderSections && (
                  <div className="mb-3">
                    <Notice tone="blue">
                      You&apos;re editing the full prompt. Changes here aren&apos;t copied back into the sections — switch to &quot;Edit by section&quot; to keep using
                      section tools.
                    </Notice>
                  </div>
                )}
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-medium text-zinc-700">System prompt</span>
                  <div className="flex flex-wrap items-center gap-1">
                    <span className="text-[11px] text-zinc-400">Insert:</span>
                    {VARIABLES.map((v) => (
                      <button
                        key={v}
                        onClick={() => insertVariable(v)}
                        className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 hover:bg-brand-50 hover:text-brand-700"
                      >
                        {`{{${v}}}`}
                      </button>
                    ))}
                  </div>
                </div>
                <Textarea
                  ref={promptRef}
                  rows={22}
                  value={draft.system_prompt}
                  onChange={(e) => set("system_prompt", e.target.value)}
                  className="font-mono text-[13px]"
                />
                <p className="mt-1 text-xs text-zinc-500">
                  Variables are filled from each lead (any extra CSV column works too, e.g. <code>{"{{city}}"}</code>). {draft.system_prompt.length.toLocaleString()} chars
                </p>
              </div>
              )}
            </div>
          )}

          {section === "knowledge" && (
            <div className="space-y-4">
              <div className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3 sm:flex-row sm:items-center">
                <BookOpen className="hidden h-5 w-5 shrink-0 text-brand-600 sm:block" />
                <div className="min-w-0 flex-1 text-xs text-zinc-600">
                  <div className="text-sm font-medium text-zinc-900">Business knowledge is shared by every agent</div>
                  Your services, hours, pricing and FAQs live in one place. Use the notes below only for things specific to this agent.
                </div>
                <Link
                  href="/knowledge"
                  className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium hover:bg-zinc-50"
                >
                  Business knowledge <ArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              </div>
              <Notice tone="blue">
                Agent-specific notes: paste FAQs, pricing, product details, policies or objection handling. The agent treats this as its source of
                truth and won&apos;t invent facts beyond it.
              </Notice>
              <div className="flex justify-end">
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium hover:bg-zinc-50">
                  <Upload className="h-3.5 w-3.5" /> Upload .txt / .md / .csv
                  <input
                    type="file"
                    accept=".txt,.md,.csv,.json"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) onKbFile(f);
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              <Textarea
                rows={24}
                value={draft.knowledge_base}
                onChange={(e) => set("knowledge_base", e.target.value)}
                placeholder="Q: How much does it cost?&#10;A: Plans start at $99/month…"
                className="font-mono text-[13px]"
              />
              <p className="text-xs text-zinc-500">
                {draft.knowledge_base.length.toLocaleString()} chars
                {draft.knowledge_base.length > 40000 && " — very long knowledge bases slow responses; keep the essentials."}
              </p>
            </div>
          )}

          {section === "voice" && <VoiceModelSettings draft={draft} set={set} voices={voices} />}

          {section === "actions" && (
            <div className="space-y-5">
              <Toggle
                checked={draft.ai_disclosure ?? false}
                onChange={(v) => set("ai_disclosure", v)}
                label="Tell callers they're speaking with an AI"
                description="The agent says it's an AI assistant near the start of the call. Recommended — some states and countries require it."
              />
              <Toggle
                checked={draft.enable_booking}
                onChange={(v) => set("enable_booking", v)}
                label="Book appointments"
                description="Gives the agent check_availability + book_appointment tools. Uses Cal.com when configured, otherwise realistic mock slots."
              />
              {draft.enable_booking && (
                <Field label="Cal.com event type ID (optional)" hint="Overrides CALCOM_EVENT_TYPE_ID for this agent.">
                  <Input value={draft.calcom_event_type_id} onChange={(e) => set("calcom_event_type_id", e.target.value.trim())} placeholder="e.g. 1234567" />
                </Field>
              )}
              <Field label="Transfer to human (phone calls)" hint="If set, the agent can warm-transfer the caller to this number. E.164, e.g. +14155550123.">
                <Input value={draft.transfer_number} onChange={(e) => set("transfer_number", e.target.value.trim())} placeholder="+14155550123" />
              </Field>
              <Card className="p-4">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Wrench className="h-4 w-4 text-zinc-400" /> Tools this agent has
                </div>
                <ul className="mt-2 space-y-1 text-xs text-zinc-600">
                  <li>
                    <code>end_call</code> — always on; hangs up and records the outcome
                  </li>
                  {draft.enable_booking && (
                    <li>
                      <code>check_availability</code>, <code>book_appointment</code>
                    </li>
                  )}
                  {draft.transfer_number && (
                    <li>
                      <code>transfer_call</code> → {draft.transfer_number}
                    </li>
                  )}
                </ul>
              </Card>
            </div>
          )}

          {section === "analysis" && (
            <div className="space-y-5">
              <Notice tone="blue">After every call, AI reads the transcript and writes a summary, outcome, sentiment and the fields below to the call log.</Notice>
              <Field label="Success criteria" hint="How to judge whether a call went well.">
                <Textarea rows={2} value={draft.success_criteria} onChange={(e) => set("success_criteria", e.target.value)} />
              </Field>
              <div>
                <div className="mb-2 text-xs font-medium text-zinc-700">Data to extract</div>
                <div className="space-y-2">
                  {draft.extraction_fields.map((f, i) => (
                    <div key={i} className="flex gap-2">
                      <Input
                        value={f.name}
                        placeholder="field_name"
                        className="w-32 shrink-0 font-mono text-xs sm:w-44"
                        onChange={(e) => {
                          const next = [...draft.extraction_fields];
                          next[i] = { ...f, name: e.target.value.replace(/\s+/g, "_").toLowerCase() };
                          set("extraction_fields", next);
                        }}
                      />
                      <Input
                        value={f.description}
                        placeholder="What to extract"
                        onChange={(e) => {
                          const next = [...draft.extraction_fields];
                          next[i] = { ...f, description: e.target.value };
                          set("extraction_fields", next);
                        }}
                      />
                      <Button
                        variant="ghost"
                        aria-label="Remove field"
                        onClick={() => set("extraction_fields", draft.extraction_fields.filter((_, j) => j !== i))}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
                <Button size="sm" className="mt-2" onClick={() => set("extraction_fields", [...draft.extraction_fields, { name: "", description: "" }])}>
                  <Plus className="h-3.5 w-3.5" /> Add field
                </Button>
              </div>
            </div>
          )}
          </div>
        </div>

        {/* Test panel */}
        <div ref={testPanelRef} tabIndex={-1} className="scroll-mt-32 focus:outline-none xl:sticky xl:top-20 xl:self-start">
          <Card className="flex h-[640px] flex-col p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Test your agent</h3>
              {dirty && <span className="text-[11px] text-amber-600">Unsaved edits save on test</span>}
            </div>
            <Tabs
              value={testTab}
              onChange={setTestTab}
              tabs={[
                { value: "voice", label: "Voice", icon: <Mic className="h-3.5 w-3.5" /> },
                { value: "chat", label: "Chat", icon: <MessageSquare className="h-3.5 w-3.5" /> },
                { value: "phone", label: "Phone", icon: <Phone className="h-3.5 w-3.5" /> },
              ]}
            />
            {testTab !== "phone" && (
              <details className="mt-3 rounded-lg border border-zinc-200 px-3 py-2 text-xs">
                <summary className="cursor-pointer font-medium text-zinc-600">Test contact: {testVars.name || "—"} · {testVars.company || "—"}</summary>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {(["name", "company", "email", "role"] as const).map((k) => (
                    <Input key={k} placeholder={k} value={testVars[k] ?? ""} onChange={(e) => setTestVars((v) => ({ ...v, [k]: e.target.value }))} className="h-8 text-xs" />
                  ))}
                </div>
              </details>
            )}
            <div className="mt-3 min-h-0 flex-1">
              {testTab === "voice" && <WebCallPanel agentId={id} enabled={!!caps?.web_call} variables={testVars} beforeStart={beforeTest} />}
              {testTab === "chat" && (
                <ChatPanel
                  key={`${saved?.first_message}|${testVars.name}|${testVars.company}`}
                  agentId={id}
                  firstMessage={saved?.first_message ?? ""}
                  enabled={!!caps?.chat_test}
                  variables={testVars}
                  beforeStart={beforeTest}
                />
              )}
              {testTab === "phone" && <PhonePanel agentId={id} enabled={!!caps?.phone_call} beforeStart={beforeTest} />}
            </div>
          </Card>
        </div>
      </div>

      <Modal open={blockersOpen} onClose={() => setBlockersOpen(false)} title="Fix these before going live">
        <p className="text-sm text-zinc-600">
          This agent can&apos;t be set to Active yet. You can keep testing it while it&apos;s paused.
        </p>
        <div className="mt-2">
          <CheckList checks={blockers} onSection={goToSection} />
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={() => setBlockersOpen(false)}>Got it</Button>
        </div>
      </Modal>
    </div>
  );
}
