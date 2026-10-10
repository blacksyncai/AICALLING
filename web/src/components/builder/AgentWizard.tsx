"use client";

import { ArrowLeft, ArrowRight, Check, CloudOff, Loader2, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Card, EmptyState, Spinner } from "@/components/ui";
import { ApiError, api, fetcher, patch, post } from "@/lib/api";
import type { AgentDraft, BuilderCatalog, BusinessProfile, DraftData } from "@/lib/builder";
import { StepBusiness } from "./StepBusiness";
import { StepGoal } from "./StepGoal";
import { StepPersonality, bookingStatus, type VoicesResponse } from "./StepPersonality";
import { GenerateError, Generating, StepReview } from "./StepReview";
import { StepTools } from "./StepTools";
import { StepProgress, STEPS, put } from "./parts";

const AUTOSAVE_MS = 800;
const POLL_MS = 1500;
const LAST_STEP = 5; // step 6 ("Done") is the redirect to the new agent

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

export function AgentWizard() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();

  const { data: catalog, error: catalogError } = useSWR<BuilderCatalog>("/api/agent-builder/catalog", fetcher, { revalidateOnFocus: false });
  const { data: voices } = useSWR<VoicesResponse>("/api/settings/voices", fetcher, { revalidateOnFocus: false });

  const [draftId, setDraftId] = useState<string | null>(null);
  const [data, setData] = useState<DraftData>({});
  const [step, setStep] = useState(1);
  const [profile, setProfile] = useState<BusinessProfile | null>(null);
  const [loadError, setLoadError] = useState("");
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState("");
  const [transferOn, setTransferOnState] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  // Autosave bookkeeping (refs so saves always send the newest state).
  const draftRef = useRef<string | null>(null);
  const latest = useRef({ step, data });
  const dirty = useRef(false);
  const hydrated = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const chain = useRef<Promise<void>>(Promise.resolve());

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
        if (draft.agent_id) {
          router.replace(`/agents/${draft.agent_id}`);
          return;
        }
        let d: DraftData = draft.data ?? {};
        if (prof?.exists) {
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
        setData(d);
        setStep(Math.min(Math.max(draft.step || 1, 1), LAST_STEP));
        setTransferOnState(!!d.behavior?.transfer_number);
        setDraftId(draft.id);
        draftRef.current = draft.id;
        if (params.get("draft") !== draft.id) router.replace(`/agents/new?draft=${draft.id}`, { scroll: false });
      } catch (e) {
        setLoadError((e as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Autosave (debounced PATCH of {step, data}) ---------------------------------------

  const save = useCallback(() => {
    chain.current = chain.current.then(async () => {
      const id = draftRef.current;
      if (!dirty.current || !id) return;
      dirty.current = false;
      setSaveState("saving");
      try {
        await patch<AgentDraft>(`/api/agent-builder/drafts/${id}`, latest.current);
        setSaveState(dirty.current ? "pending" : "saved");
      } catch {
        dirty.current = true;
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
    latest.current = { step, data };
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

  // ---- Sensible defaults for the personality step ----------------------------------------
  useEffect(() => {
    if (step !== 3 || !catalog) return;
    setData((d) => {
      if (d.behavior?.language) return d;
      const booking = bookingStatus(catalog);
      return {
        ...d,
        behavior: {
          language: "en",
          style: catalog.styles[0]?.key,
          qualification_depth: "standard",
          booking: booking === "available",
          callback: true,
          ai_disclosure: true,
          ...d.behavior,
        },
      };
    });
  }, [step, catalog]);

  // ---- Helpers -----------------------------------------------------------------------------
  const business = data.business ?? {};
  const behavior = data.behavior ?? {};

  function setTransferOn(v: boolean) {
    setTransferOnState(v);
    if (!v) setData((d) => ({ ...d, behavior: { ...d.behavior, transfer_number: "", transfer_when: "" } }));
  }

  function invalid(n: number): boolean {
    if (n === 1) return !business.name?.trim() || !business.industry;
    if (n === 2) return !data.goal?.direction || !data.goal?.use_case;
    if (n === 3) return !behavior.agent_name?.trim() || (transferOn && !behavior.transfer_number?.trim());
    return false;
  }

  function go(n: number) {
    setShowErrors(false);
    setStep(n);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function next() {
    if (invalid(step)) {
      setShowErrors(true);
      return;
    }
    if (step === 1) {
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
    go(step + 1);
  }

  async function generate() {
    for (const n of [1, 2, 3]) {
      if (invalid(n)) {
        go(n);
        setShowErrors(true);
        return;
      }
    }
    setGenError("");
    setGenerating(true);
    try {
      await flush();
      const res = await post<{ agent_id: string }>("/api/agent-builder/generate", { draft_id: draftRef.current });
      setStep(6);
      router.push(`/agents/${res.agent_id}?created=1`);
    } catch (e) {
      setGenError((e as Error).message);
      setGenerating(false);
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

  const hasKnowledge = (profile?.item_count ?? 0) > 0;
  const primaryLabel =
    step === 1
      ? hasKnowledge
        ? "Looks good, continue"
        : "Continue"
      : step === 4 && !(data.integrations?.selected ?? []).length
        ? "Skip for now"
        : "Continue";

  return (
    <div className="mx-auto max-w-3xl">
      {/* Top bar */}
      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg brand-gradient text-white">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <h1 className="truncate font-display text-base font-semibold tracking-tight text-zinc-900">New agent</h1>
          <SaveIndicator state={saveState} />
        </div>
        <Button size="sm" variant="ghost" onClick={saveAndExit} disabled={generating || busy}>
          Save &amp; exit
        </Button>
      </div>

      <div className="mb-6">
        <StepProgress step={step} />
      </div>

      {catalogError && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">Some options couldn&apos;t load: {(catalogError as Error).message}</p>
      )}

      <Card className="overflow-hidden">
        {generating ? (
          <Generating />
        ) : (
          <div key={step} className="p-5 transition duration-300 ease-out starting:translate-y-2 starting:opacity-0 sm:p-8">
            {step === 1 && (
              <StepBusiness
                business={business}
                onChange={(p) => setData((d) => ({ ...d, business: { ...d.business, ...p } }))}
                catalog={catalog}
                profile={profile}
                onProfile={setProfile}
                showErrors={showErrors}
              />
            )}
            {step === 2 && (
              <StepGoal
                goal={data.goal ?? {}}
                onChange={(goal) => setData((d) => ({ ...d, goal }))}
                catalog={catalog}
                industry={business.industry}
                showErrors={showErrors}
              />
            )}
            {step === 3 && (
              <StepPersonality
                behavior={behavior}
                onChange={(p) => setData((d) => ({ ...d, behavior: { ...d.behavior, ...p } }))}
                catalog={catalog}
                voices={voices}
                transferOn={transferOn}
                setTransferOn={setTransferOn}
                showErrors={showErrors}
              />
            )}
            {step === 4 && (
              <StepTools
                selected={data.integrations?.selected ?? []}
                onChange={(selected) => setData((d) => ({ ...d, integrations: { ...d.integrations, selected } }))}
                catalog={catalog}
                industry={business.industry}
              />
            )}
            {step === 5 && <StepReview data={data} catalog={catalog} profile={profile} voices={voices} onEdit={go} />}
            {step === 5 && genError && <GenerateError message={genError} onRetry={generate} />}
          </div>
        )}
      </Card>

      {/* Actions */}
      {!generating && (
        <div className="sticky bottom-0 z-10 -mx-4 mt-4 flex items-center justify-between gap-3 border-t border-zinc-200 bg-white/90 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:px-0 sm:py-0 sm:backdrop-blur-none">
          {step > 1 ? (
            <Button variant="ghost" onClick={() => go(step - 1)} disabled={busy}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-3">
            {step === 1 && analyzing && (
              <button type="button" onClick={next} className="text-xs font-medium text-zinc-500 hover:text-zinc-800">
                Continue without waiting
              </button>
            )}
            {step === LAST_STEP ? (
              <Button variant="primary" onClick={generate}>
                <Sparkles className="h-4 w-4" /> Generate my agent
              </Button>
            ) : (
              <Button variant="primary" onClick={next} loading={busy} disabled={step === 1 && analyzing}>
                {step === 1 && hasKnowledge && !busy && <Check className="h-4 w-4" />}
                {step === 1 && analyzing ? "Analyzing…" : primaryLabel}
                {!busy && !(step === 1 && hasKnowledge) && <ArrowRight className="h-4 w-4" />}
              </Button>
            )}
          </div>
        </div>
      )}
      {showErrors && invalid(step) && (
        <p className="mt-2 text-right text-xs text-red-600" role="alert">
          Please fill in the highlighted fields to continue to {STEPS[step]}.
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
