"use client";

import { ArrowLeft, ArrowRight, Check, CloudOff, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Card, EmptyState, Spinner } from "@/components/ui";
import { ApiError, api, fetcher, patch, post } from "@/lib/api";
import {
  CUSTOM_USE_CASE,
  SOMETHING_ELSE,
  type AgentDraft,
  type AssistResponse,
  type BuilderCatalog,
  type BusinessProfile,
  type DraftData,
  type DraftGoal,
  type Generation,
  type ReferenceDoc,
} from "@/lib/builder";
import { MIN_DESCRIPTION, useCasesFor } from "./goal";
import { StepBusiness } from "./StepBusiness";
import { StepIdentity } from "./StepIdentity";
import { StepLaunch } from "./StepLaunch";
import { StepMission, missionReady } from "./StepMission";
import { bookingStatus, type Behavior, type VoicesResponse } from "./StepPersonality";
import { StepReferences } from "./StepReferences";
import { GenerateError, Generating } from "./StepReview";
import { Collapsible, DRAFT_VERSION, GENERATE_STEP, LAST_STEP, LAUNCH_STEP, StepProgress, STEPS, put, resumeStep } from "./parts";

const AUTOSAVE_MS = 800;
const POLL_MS = 1500;
const GEN_POLL_MS = 2000;

type SaveState = "idle" | "pending" | "saving" | "saved" | "error";

async function loadOrCreateDraft(id: string | null): Promise<AgentDraft> {
  if (id) {
    try {
      return await api<AgentDraft>(`/api/agent-builder/drafts/${id}`);
    } catch (e) {
      if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 422)) throw e;
    }
  }
  return post<AgentDraft>("/api/agent-builder/drafts", { step: 1, data: {} });
}

const ADVANCED_LABELS: [keyof NonNullable<DraftGoal["advanced"]>, string][] = [
  ["qualification", "A good lead"],
  ["questions", "Questions it must ask"],
  ["objections", "Objections to expect"],
  ["booking", "When to book"],
  ["follow_up", "Follow-up"],
];

/**
 * Turn the v4 answers (specialty, mission, advanced details) into the fields the existing generator reads
 * (use_cases, custom, extra_instructions, behavior). Nothing new on the server — one generation pipeline.
 */
export function toGeneratorInput(data: DraftData, catalog: BuilderCatalog | undefined): DraftData {
  const g = data.goal ?? {};
  const sp = g.specialty;
  const adv = g.advanced ?? {};
  const known = new Set(useCasesFor(catalog, data.business?.industry).map((u) => u.key));
  const presets = sp && sp.key !== SOMETHING_ELSE ? sp.use_cases.filter((k) => known.has(k)) : [];
  const own = sp?.key === SOMETHING_ELSE ? sp.description?.trim() : "";
  const mission = (g.mission ?? "").trim();
  const description = [own && `What the agent is: ${own}`, mission && `Mission: ${mission}`].filter(Boolean).join("\n");
  const extra = [
    ...ADVANCED_LABELS.filter(([k]) => adv[k]?.trim()).map(([k, l]) => `${l}: ${adv[k]!.trim()}`),
    g.additional?.trim(),
  ]
    .filter(Boolean)
    .join("\n");

  const b: Behavior = { ...data.behavior };
  if (b.decide_later !== false) {
    b.decide_later = true;
  } else {
    // Customized in "Advanced": fill the rest with the same defaults as the recommended settings.
    const presetActions = useCasesFor(catalog, data.business?.industry).filter((u) => presets.includes(u.key));
    const bookingLikely = presetActions.length === 0 || presetActions.some((u) => u.actions.includes("book_appointment"));
    b.qualification_depth ??= "standard";
    b.callback ??= true;
    b.ai_disclosure ??= true;
    b.booking ??= bookingStatus(catalog) === "available" && bookingLikely;
    if (!b.transfer_number?.trim()) {
      delete b.transfer_number;
      delete b.transfer_when;
    }
  }
  return {
    ...data,
    goal: {
      ...g,
      use_cases: [...presets, CUSTOM_USE_CASE],
      use_case: presets[0] ?? CUSTOM_USE_CASE,
      custom: { description, audience: adv.audience?.trim() ?? "", tone: adv.tone?.trim() ?? "", outcome: "" },
      extra_instructions: extra,
    },
    behavior: b,
  };
}

export function AgentWizard() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();

  const { data: catalog, error: catalogError } = useSWR<BuilderCatalog>("/api/agent-builder/catalog", fetcher, { revalidateOnFocus: false });
  const { data: voices } = useSWR<VoicesResponse>("/api/settings/voices", fetcher, { revalidateOnFocus: false });

  const [draftId, setDraftId] = useState<string | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [data, setData] = useState<DraftData>({});
  const [step, setStep] = useState(1);
  const [profile, setProfile] = useState<BusinessProfile | null>(null);
  const [loadError, setLoadError] = useState("");
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generation, setGeneration] = useState<Generation | null>(null);
  const [genError, setGenError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");

  // Autosave bookkeeping (refs so saves always send the newest state).
  const draftRef = useRef<string | null>(null);
  const latest = useRef({ step, data });
  const dirty = useRef(false);
  const hydrated = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const lastSaveOk = useRef(true);

  // ---- Load (or create) the draft + business profile once -------------------------------
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const [draft, prof] = await Promise.all([
          loadOrCreateDraft(params.get("draft")),
          api<BusinessProfile>("/api/business-profile").catch(() => null),
        ]);
        let d: DraftData = draft.data ?? {};
        if (prof?.exists) {
          // The org profile supplies the defaults; the customer can still change them here.
          const b = d.business ?? {};
          d = {
            ...d,
            business: {
              name: b.name || prof.name || "",
              industry: b.industry || prof.industry || undefined,
              website: b.website || prof.website || "",
              description: b.description || prof.description || "",
            },
          };
        }
        setProfile(prof);
        setData({ ...d, v: DRAFT_VERSION });
        setDraftId(draft.id);
        draftRef.current = draft.id;
        if (draft.agent_id) {
          // Already generated: go straight to test & launch (never builds a second agent).
          setAgentId(draft.agent_id);
          setStep(LAUNCH_STEP);
        } else {
          setStep(resumeStep(draft.step, draft.data));
          if (draft.generation?.status === "running") {
            setGeneration(draft.generation);
            setGenerating(true);
            setStep(GENERATE_STEP);
          }
        }
        if (params.get("draft") !== draft.id) router.replace(`/agents/new?draft=${draft.id}`, { scroll: false });
      } catch (e) {
        setLoadError((e as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A link like /agents/new?specialty=expired_listings (dashboard recommendations) picks the specialty.
  const presetDone = useRef(false);
  const wantSpecialty = useRef(params.get("specialty")); // read once: the draft redirect drops it from the URL
  useEffect(() => {
    const want = wantSpecialty.current;
    if (presetDone.current || !want || !catalog || !draftId) return;
    presetDone.current = true;
    const industry = data.business?.industry;
    const sp = (catalog.specialties?.[industry ?? ""] ?? catalog.specialties?.other ?? []).find((s) => s.key === want);
    if (sp && !data.goal?.specialty) setData((d) => ({ ...d, goal: { ...d.goal, specialty: { ...sp }, direction: sp.direction } }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, draftId]);

  // ---- Autosave (debounced PATCH of {step, data}) ---------------------------------------

  const save = useCallback(() => {
    chain.current = chain.current.then(async () => {
      const id = draftRef.current;
      if (!dirty.current || !id) return;
      dirty.current = false;
      setSaveState("saving");
      try {
        await patch<AgentDraft>(`/api/agent-builder/drafts/${id}`, latest.current);
        lastSaveOk.current = true;
        setSaveState(dirty.current ? "pending" : "saved");
      } catch {
        dirty.current = true;
        lastSaveOk.current = false;
        setSaveState("error");
      }
    });
    return chain.current;
  }, []);

  const flush = useCallback(() => {
    clearTimeout(timer.current);
    return save();
  }, [save]);

  useEffect(() => {
    latest.current = { step: Math.min(step, LAST_STEP), data };
    if (!draftId) return;
    if (!hydrated.current) {
      hydrated.current = true;
      return;
    }
    if (step > LAST_STEP) return;
    dirty.current = true;
    setSaveState("pending");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void save(), AUTOSAVE_MS);
  }, [step, data, draftId, save]);

  // The quick-check questions on the Mission step read the saved draft, so save first.
  const runAssist = useCallback(
    async (g: DraftGoal) => {
      latest.current = { ...latest.current, data: { ...latest.current.data, goal: g } };
      dirty.current = true;
      await flush();
      if (!lastSaveOk.current) throw new Error("We couldn't save your answers. Check your connection and try again.");
      return post<AssistResponse>("/api/agent-builder/assist", { draft_id: draftRef.current });
    },
    [flush],
  );

  // Save whatever is pending if the user leaves through the sidebar.
  useEffect(() => () => void flush(), [flush]);

  // ---- Poll the business profile while the website is being analyzed ---------------------
  const analyzing = profile?.status === "analyzing";
  useEffect(() => {
    if (!analyzing) return;
    const t = setInterval(async () => {
      try {
        setProfile(await api<BusinessProfile>("/api/business-profile"));
      } catch {
        /* keep polling */
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [analyzing]);

  // ---- Follow a running generation job until it finishes ---------------------------------
  useEffect(() => {
    if (!generating || !draftId) return;
    let stopped = false;
    const tick = async () => {
      try {
        const g = await api<Generation>(`/api/agent-builder/drafts/${draftId}/generation`);
        if (stopped) return;
        setGeneration(g);
        if (g.status === "done" && g.agent_id) {
          stopped = true;
          setAgentId(g.agent_id);
          setGenerating(false);
          setStep(LAUNCH_STEP);
          window.scrollTo({ top: 0, behavior: "smooth" });
        } else if (g.status === "failed") {
          stopped = true;
          setGenError(g.error || "Something went wrong. Please try again.");
          setGenerating(false);
        }
      } catch {
        /* keep polling through brief network hiccups */
      }
    };
    const t = setInterval(tick, GEN_POLL_MS);
    void tick();
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }, [generating, draftId]);

  const { data: refs } = useSWR<{ references: ReferenceDoc[] }>(
    draftId && step === LAUNCH_STEP ? `/api/agent-builder/drafts/${draftId}/references` : null,
    fetcher,
  );

  // ---- Helpers -----------------------------------------------------------------------------
  const business = data.business ?? {};
  const behavior = data.behavior ?? {};
  const goal = data.goal ?? {};

  const setGoal = useCallback((fn: (g: DraftGoal) => DraftGoal) => setData((d) => ({ ...d, goal: fn(d.goal ?? {}) })), []);
  const setBusiness = useCallback((p: Partial<NonNullable<DraftData["business"]>>) => setData((d) => ({ ...d, business: { ...d.business, ...p } })), []);
  const setBehavior = useCallback((p: Partial<Behavior>) => setData((d) => ({ ...d, behavior: { ...d.behavior, ...p } })), []);

  function invalid(n: number): boolean {
    if (n === 1) {
      const sp = goal.specialty;
      if (!business.name?.trim() || !business.industry || !sp) return true;
      return sp.key === SOMETHING_ELSE && (sp.description ?? "").trim().length < MIN_DESCRIPTION;
    }
    if (n === 3) return !missionReady(goal) || (behavior.transfer_number !== undefined && !behavior.transfer_number.trim());
    return false;
  }

  function go(n: number) {
    setShowErrors(false);
    setGenError("");
    setStep(n);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function next() {
    if (invalid(step)) {
      setShowErrors(true);
      return;
    }
    if (step === 1) {
      // Keep the org profile in step with what was confirmed here (the website analyzer reads it).
      setBusy(true);
      try {
        const p = await put<BusinessProfile>("/api/business-profile", {
          name: business.name?.trim() ?? "",
          industry: business.industry ?? "",
          website: business.website?.trim() ?? "",
          description: business.description?.trim() ?? "",
        });
        setProfile(p);
      } catch (e) {
        toast((e as Error).message, "error");
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    if (step === LAST_STEP) return generate();
    go(step + 1);
  }

  async function generate() {
    for (const n of [1, 3]) {
      if (invalid(n)) {
        go(n);
        setShowErrors(true);
        return;
      }
    }
    setGenError("");
    const input = toGeneratorInput(data, catalog);
    setData(input);
    latest.current = { step: LAST_STEP, data: input };
    dirty.current = true;
    await flush();
    if (!lastSaveOk.current) {
      setGenError("We couldn't save your answers. Check your connection.");
      return;
    }
    setStep(GENERATE_STEP);
    window.scrollTo({ top: 0, behavior: "smooth" });
    try {
      const g = await post<Generation>("/api/agent-builder/generate", { draft_id: draftRef.current });
      setGeneration(g);
      if (g.status === "done" && g.agent_id) {
        setAgentId(g.agent_id);
        setStep(LAUNCH_STEP);
        return;
      }
      setGenerating(true);
    } catch (e) {
      setGenError((e as Error).message);
    }
  }

  async function saveAndExit() {
    setBusy(true);
    await flush();
    setBusy(false);
    if (dirty.current) {
      toast("We couldn't save your latest changes. Check your connection and try again.", "error");
      return;
    }
    toast("Draft saved. Pick up where you left off from New agent.");
    router.push("/agents");
  }

  // ---- Render ------------------------------------------------------------------------------
  if (loadError) {
    return (
      <div className="mx-auto max-w-3xl">
        <Card>
          <EmptyState
            icon={<CloudOff className="h-5 w-5" />}
            title="We couldn't start the builder"
            description={loadError}
            action={<Button onClick={() => window.location.reload()}>Try again</Button>}
          />
        </Card>
      </div>
    );
  }

  if (!draftId) {
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  }

  const filling = step <= LAST_STEP;
  const wide = step === LAUNCH_STEP;

  return (
    <div className={wide ? "mx-auto max-w-5xl" : "mx-auto max-w-3xl"}>
      {/* Top bar */}
      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg brand-gradient text-white">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <h1 className="truncate font-display text-base font-semibold tracking-tight text-zinc-900">Build with AI</h1>
          {filling && <SaveIndicator state={saveState} />}
        </div>
        {filling ? (
          <Button size="sm" variant="ghost" onClick={saveAndExit} disabled={busy}>
            Save &amp; exit
          </Button>
        ) : step === LAUNCH_STEP ? (
          <Link href="/agents" className="text-xs font-medium text-zinc-500 hover:text-zinc-900">
            Back to agents
          </Link>
        ) : null}
      </div>

      <div className="mb-6">
        <StepProgress step={step} />
      </div>

      {catalogError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">Some options couldn&apos;t load: {(catalogError as Error).message}</p>
      )}

      <Card className="overflow-hidden">
        {step === GENERATE_STEP ? (
          genError ? (
            <div className="p-5 sm:p-8">
              <GenerateError message={genError} onRetry={generate} />
              <button type="button" onClick={() => go(LAST_STEP)} className="mt-3 text-xs font-medium text-zinc-600 hover:text-zinc-900">
                Back to your answers
              </button>
            </div>
          ) : (
            <Generating generation={generation} />
          )
        ) : (
          <div key={step} className="p-5 transition duration-300 ease-out starting:translate-y-2 starting:opacity-0 sm:p-8">
            {step === 1 && (
              <StepIdentity
                business={business}
                onBusiness={setBusiness}
                goal={goal}
                setGoal={setGoal}
                behavior={behavior}
                onBehavior={setBehavior}
                catalog={catalog}
                voices={voices}
                showErrors={showErrors}
              />
            )}
            {step === 2 && (
              <div className="space-y-4">
                <StepBusiness business={business} onChange={setBusiness} catalog={catalog} profile={profile} onProfile={setProfile} showErrors={false} knowledgeOnly />
                <Collapsible title="Scripts or notes (optional)" meta="Upload or paste">
                  <StepReferences draftId={draftId} />
                </Collapsible>
              </div>
            )}
            {step === 3 && (
              <StepMission
                draftId={draftId}
                goal={goal}
                setGoal={setGoal}
                behavior={behavior}
                onBehavior={setBehavior}
                catalog={catalog}
                flush={flush}
                runAssist={runAssist}
                showErrors={showErrors}
              />
            )}
            {step === LAUNCH_STEP && agentId && (
              <StepLaunch agentId={agentId} catalog={catalog} profile={profile} voices={voices} references={refs?.references.length ?? 0} />
            )}
          </div>
        )}
      </Card>

      {/* Actions — in the page flow on mobile so they never cover the form */}
      {filling && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          {step > 1 ? (
            <Button variant="ghost" onClick={() => go(step - 1)} disabled={busy}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
          ) : (
            <span />
          )}
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 sm:gap-3">
            {step === 2 && analyzing && <span className="text-xs text-zinc-500">You can continue while we read your site.</span>}
            {step === 2 && !analyzing && !(profile?.item_count ?? 0) && (
              <button type="button" onClick={() => go(3)} className="text-xs font-medium text-zinc-500 hover:text-zinc-800">
                Continue without a website
              </button>
            )}
            <Button variant="primary" onClick={next} loading={busy}>
              {step === LAST_STEP ? (
                <>
                  <Sparkles className="h-4 w-4" /> Build my agent
                </>
              ) : (
                <>
                  Continue <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </div>
        </div>
      )}
      {filling && showErrors && invalid(step) && (
        <p className="mt-2 text-right text-xs text-red-600" role="alert">
          Please fill in the highlighted fields to continue{step < LAST_STEP ? ` to ${STEPS[step]}` : ""}.
        </p>
      )}
    </div>
  );
}

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === "idle") return null;
  return (
    <span className="hidden items-center gap-1 text-xs text-zinc-400 sm:inline-flex" aria-live="polite">
      {state === "saving" || state === "pending" ? (
        <>
          <Loader2 className="h-3 w-3 animate-spin" /> Saving
        </>
      ) : state === "saved" ? (
        <>
          <Check className="h-3 w-3" /> Saved
        </>
      ) : (
        <span className="text-amber-600">Not saved — retrying when you make a change</span>
      )}
    </span>
  );
}
