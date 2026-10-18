"use client";

import { ArrowLeft, ArrowUpRight, BookOpen, Brain, Check, Eye, MessageSquare, Mic, Phone, Plus, Sparkles, Trash2, Upload, Wrench, Zap } from "lucide-react";
import MatteAlertFeedback from "@/components/ui/matte-alert-feedback";
import { AnimatedTabList, AnimatedTabPanel } from "@/components/ui/animated-tabs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { ChatPanel } from "@/components/agent/ChatPanel";
import { CallFromSettings } from "@/components/agent/CallFromSettings";
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
import { Badge, Button, Card, Field, Input, Modal, Notice, Select, Spinner, Tabs, Textarea, Toggle } from "@/components/ui";
import { fetcher, patch } from "@/lib/api";
import type { Agent, SettingsStatus, Voice } from "@/lib/types";
import { cn } from "@/lib/utils";

type Section = "prompt" | "knowledge" | "voice" | "model" | "actions" | "analysis";
type TestTab = "voice" | "chat" | "phone";

const SECTIONS: { value: Section; label: string; icon: typeof Brain }[] = [
  { value: "prompt", label: "Prompt", icon: Brain },
  { value: "voice", label: "Voice", icon: Mic },
  { value: "model", label: "Model / Brain", icon: Brain },
  { value: "actions", label: "Actions", icon: Zap },
  { value: "knowledge", label: "Knowledge", icon: BookOpen },
  { value: "analysis", label: "Post-call analysis", icon: Sparkles },
];

const VARIABLES = ["name", "full_name", "company", "email", "phone", "role"];

const EDITABLE: (keyof Agent)[] = [
  "name", "description", "status", "system_prompt", "first_message", "knowledge_base", "language",
  "llm_model", "temperature", "voice_id", "voice_speed", "voice_tuning", "background_audio", "enable_booking",
  "calcom_event_type_id", "calcom_api_key", "calendar_timezone", "voicemail_action", "voicemail_message", "transfer_number", "max_duration_seconds", "extraction_fields", "success_criteria",
  "ai_disclosure", "builder", "caller_number", "record_calls", "specialty",
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
  voice: "voice", model: "model",
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
  const testContact = saved?.builder?.test_contact;
  // Agents with their own demo contact (the FSBO agent's homeowner) test with it.
  const testContactKey = JSON.stringify(testContact ?? null);
  useEffect(() => {
    const contact = JSON.parse(testContactKey) as Record<string, string> | null;
    if (contact) setTestVars(contact);
  }, [testContactKey]);
  const testKeys = testContact ? Object.keys(testContact) : (["name", "company", "email", "role"] as string[]);
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
          <div ref={editorRef} className="agent-glass scroll-mt-32 rounded-2xl p-3 sm:p-5">
          <AnimatedTabList
            tabs={SECTIONS.map(({ value, label, icon: Icon }) => ({ id: value, label, icon: <Icon className="h-4 w-4" /> }))}
            value={section}
            onChange={setSection}
            variant="dark"
            layoutId="agent-editor-tab"
            className="mb-5 grid! grid-cols-3 [&>button]:min-w-0 [&>button]:justify-center [&>button]:px-2! [&>button]:text-xs! sm:flex! sm:flex-wrap! sm:[&>button]:text-sm!"
          />

          <AnimatedTabPanel key={section}>
          {section === "prompt" && (
            <div className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
                <Field label="Specialty" hint="Badge in your agent list. Yours stays when the agent is regenerated.">
                  <Input value={draft.specialty ?? ""} onChange={(e) => set("specialty", e.target.value)} maxLength={60} placeholder="e.g. Expired Listings" />
                </Field>
                <Field label="Description" hint="Internal note — not used by the agent.">
                  <Input value={draft.description} onChange={(e) => set("description", e.target.value)} />
                </Field>
              </div>
              <Field label="First message" hint="Spoken word-for-word, all in one go, as soon as the call connects — so if it asks a question, put the question last. Leave empty to let the agent improvise.">
                <p className="mb-2 text-sm font-semibold text-[#ff3333]">We suggest leaving the First message section blank for outbound agents.</p>
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

          {section === "voice" && <VoiceModelSettings key="voice" draft={draft} set={set} voices={voices} view="voice" />}
          {section === "model" && <VoiceModelSettings key="model" draft={draft} set={set} voices={voices} view="model" />}

          {section === "actions" && (
            <div className="space-y-5">
              <Link href="/radar#assistant" className="flex items-center justify-between gap-3 rounded-xl border border-brand-200 bg-brand-50 p-4 hover:border-brand-400">
                <div><div className="text-sm font-semibold">Tell your agent what to do after a call</div>
                  <p className="mt-1 text-xs text-zinc-600">Open Radar’s CRM Assistant to set up notes, follow-ups and CRM updates.</p></div>
                <ArrowUpRight className="h-4 w-4 shrink-0" />
              </Link>
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
                description="The agent can check your calendar for open times and book the meeting straight into your Cal.com calendar."
              />
              {draft.enable_booking && <CalcomSettings draft={draft} set={set} />}
              <VoicemailSettings draft={draft} set={set} />
              <CallFromSettings draft={draft} set={set} />
              <Field label="Transfer to human (phone calls)" hint="Direct transfer on phone calls only; browser tests cannot transfer. Enter a full number, e.g. +14155550123. The caller hears ringing while your teammate answers.">
                <Input value={draft.transfer_number} onChange={(e) => set("transfer_number", e.target.value.trim())} placeholder="+14155550123" />
              </Field>
              <Card className="p-4">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Wrench className="h-4 w-4 text-zinc-400" /> What this agent can do on a call
                </div>
                <ul className="mt-2 space-y-1 text-xs text-zinc-600">
                  <li>
                    Hang up — always on; ends the call and records the result
                  </li>
                  {draft.enable_booking && (
                    <li>
                      Check your calendar and book appointments
                    </li>
                  )}
                  {draft.transfer_number && (
                    <li>
                      Transfer the call to {draft.transfer_number}
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
          </AnimatedTabPanel>
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
                <summary className="cursor-pointer font-medium text-zinc-600">Test contact: {testVars.name || "—"} · {(testContact ? testVars[testKeys[1]] : testVars.company) || "—"}</summary>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {testKeys.map((k) => (
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
              {testTab === "phone" && <PhonePanel agentId={id} enabled={!!caps?.phone_call} beforeStart={beforeTest} callerNumber={draft.caller_number} />}
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

const TIMEZONES: string[] = (() => {
  try {
    return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
  } catch {
    return ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Europe/London", "UTC"];
  }
})();

const US_TIMEZONES: { value: string; label: string }[] = [
  { value: "America/New_York", label: "Eastern (New York)" },
  { value: "America/Chicago", label: "Central (Chicago)" },
  { value: "America/Denver", label: "Mountain (Denver)" },
  { value: "America/Phoenix", label: "Arizona (Phoenix, no DST)" },
  { value: "America/Los_Angeles", label: "Pacific (Los Angeles)" },
  { value: "America/Anchorage", label: "Alaska (Anchorage)" },
  { value: "Pacific/Honolulu", label: "Hawaii (Honolulu)" },
  { value: "America/Puerto_Rico", label: "Atlantic (Puerto Rico)" },
];

/** US zones up front; any other IANA zone can be searched by name. */
function TimezonePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const known = !value || US_TIMEZONES.some((z) => z.value === value);
  const [other, setOther] = useState(!known);
  const [query, setQuery] = useState(known ? "" : value);
  return (
    <Field label="Time zone" hint="Times are offered and booked in this zone.">
      <div className="space-y-2">
        <Select
          value={other ? "__other" : value}
          onChange={(e) => {
            if (e.target.value === "__other") {
              setOther(true);
            } else {
              setOther(false);
              onChange(e.target.value);
            }
          }}
        >
          <option value="">Pick a time zone…</option>
          {US_TIMEZONES.map((z) => (
            <option key={z.value} value={z.value}>
              {z.label}
            </option>
          ))}
          <option value="__other">Other time zone…</option>
        </Select>
        {other && (
          <>
            <Input
              list="tz-list"
              placeholder="Search, e.g. Toronto or Europe/London"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                if (TIMEZONES.includes(e.target.value)) onChange(e.target.value);
              }}
            />
            <datalist id="tz-list">
              {TIMEZONES.map((z) => (
                <option key={z} value={z}>
                  {z.replace(/_/g, " ")}
                </option>
              ))}
            </datalist>
          </>
        )}
      </div>
    </Field>
  );
}

/** Cal.com key (write-only), event type and the time zone the agent says times in. */
function CalcomSettings({ draft, set }: { draft: Agent; set: <K extends keyof Agent>(key: K, value: Agent[K]) => void }) {
  const keySaved = !!draft.calcom_key_set && draft.calcom_api_key === undefined;
  const removing = draft.calcom_api_key === "";
  const ready = (keySaved || !!draft.calcom_api_key) && !!draft.calcom_event_type_id;
  const tz = draft.calendar_timezone ?? "";
  return (
    <Card className="space-y-4 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium">Cal.com calendar</div>
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", ready ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>
          {ready ? "Connected" : "Needs API key and event type"}
        </span>
      </div>
      <Field
        label="Cal.com API key"
        hint={
          removing ? "The saved key will be removed when you save." : keySaved ? "A key is saved. Paste a new one to replace it." : "Cal.com → Settings → Developer → API keys."
        }
      >
        <div className="flex gap-2">
          <Input
            type="password"
            autoComplete="off"
            value={draft.calcom_api_key ?? ""}
            placeholder={keySaved ? "•••••••• saved" : "cal_live_…"}
            onChange={(e) => set("calcom_api_key", e.target.value.trim() || undefined)}
          />
          {draft.calcom_key_set && !removing && (
            <button type="button" onClick={() => set("calcom_api_key", "")} className="shrink-0 rounded-lg px-3 text-sm text-zinc-500 hover:bg-zinc-100 hover:text-red-600">
              Remove
            </button>
          )}
        </div>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Event type ID" hint="The number in the event type's URL in Cal.com.">
          <Input inputMode="numeric" value={draft.calcom_event_type_id} onChange={(e) => set("calcom_event_type_id", e.target.value.replace(/\D/g, ""))} placeholder="e.g. 4374694" />
        </Field>
        <TimezonePicker value={tz} onChange={(v) => set("calendar_timezone", v)} />
      </div>
    </Card>
  );
}

const VOICEMAIL_OPTIONS: { value: NonNullable<Agent["voicemail_action"]>; label: string; hint: string }[] = [
  { value: "hang_up", label: "Hang up", hint: "End the call after the minimum connected time." },
  { value: "leave_message", label: "Leave a message", hint: "Wait for the beep, say your message, then hang up." },
  { value: "ignore", label: "Keep talking", hint: "Treat it like a normal call (not recommended)." },
];

/** What a phone call does when an answering machine picks up. */
function VoicemailSettings({ draft, set }: { draft: Agent; set: <K extends keyof Agent>(key: K, value: Agent[K]) => void }) {
  const action = draft.voicemail_action ?? "hang_up";
  return (
    <Card className="space-y-4 p-4">
      <div>
        <div className="text-sm font-medium">When voicemail picks up</div>
        <p className="mt-0.5 text-xs text-zinc-500">The agent listens for an answering-machine greeting in the first seconds of a phone call.</p>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {VOICEMAIL_OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => set("voicemail_action", o.value)}
            aria-pressed={action === o.value}
            className={cn(
              "rounded-xl border p-3 text-left transition-colors",
              action === o.value ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-zinc-200 hover:border-zinc-300",
            )}
          >
            <div className="text-sm font-medium text-zinc-900">{o.label}</div>
            <div className="mt-0.5 text-xs text-zinc-500">{o.hint}</div>
          </button>
        ))}
      </div>
      {action !== "ignore" && (
        <Field label="Minimum connected time (seconds)" hint="Wait silently until this much time has passed since answer before ending a voicemail call. Default: 6.2 seconds. Carrier charges still apply.">
          <Input type="number" min={0} max={60} step={0.1}
            value={draft.voice_tuning?.voicemail_min_connected_seconds ?? 6.2}
            onChange={(e) => { const value = Number(e.target.value); if (Number.isFinite(value)) set("voice_tuning", { ...draft.voice_tuning, voicemail_min_connected_seconds: Math.min(60, Math.max(0, value)) }); }} />
        </Field>
      )}
      {action === "leave_message" && (
        <Field label="Voicemail message" hint="Keep it under 30 seconds. You can use {{name}}, {{company}} and other contact fields.">
          <Textarea
            rows={3}
            maxLength={1000}
            value={draft.voicemail_message ?? ""}
            placeholder="Hi {{name}}, this is Synchro from BlackSync — sorry I missed you. I'll try you again soon, or call us back at this number. Thanks!"
            onChange={(e) => set("voicemail_message", e.target.value)}
          />
        </Field>
      )}
      {action === "leave_message" && !(draft.voicemail_message ?? "").trim() && (
        <p className="text-xs text-amber-700">Add a message, otherwise the agent will just hang up.</p>
      )}
      {action === "ignore" && (
        <MatteAlertFeedback
          cardTitle="Voicemail handling"
          pillText="Keep talking"
          cardDescription="The agent will pitch to answering machines like they're a person."
          alertTitle="You'll pay AI time on every voicemail"
          alertDetail="Calls stay open until the mailbox cuts off (often 2+ minutes). Hang up or Leave a message is cheaper and sounds better."
          showControls={false}
        />
      )}
    </Card>
  );
}
