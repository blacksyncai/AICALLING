"use client";

import { AlertCircle, Check, Globe, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Field, Input, Notice } from "@/components/ui";
import { post } from "@/lib/api";
import type { BuilderCatalog, BusinessProfile, DraftData } from "@/lib/builder";
import { cn } from "@/lib/utils";
import { KnowledgeReview } from "./KnowledgeReview";
import { StepTitle, displayHost, industryIcon, normalizeUrl, put } from "./parts";
import { VoiceTextarea } from "@/components/MicButton";

type Business = NonNullable<DraftData["business"]>;

const STAGES = ["Exploring your website", "Understanding your business", "Identifying services and team details", "Preparing your knowledge base"];

export function StepBusiness({
  business,
  onChange,
  catalog,
  profile,
  onProfile,
  showErrors,
  knowledgeOnly = false,
}: {
  business: Business;
  onChange: (patch: Partial<Business>) => void;
  catalog: BuilderCatalog | undefined;
  profile: BusinessProfile | null;
  onProfile: (p: BusinessProfile) => void;
  showErrors: boolean;
  /** Wizard step 2: only the website/knowledge part (name and industry were asked in step 1). */
  knowledgeOnly?: boolean;
}) {
  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const [manual, setManual] = useState(false);
  const website = business.website ?? "";
  const status = profile?.status ?? "idle";
  const analyzing = status === "analyzing";
  const hasKnowledge = (profile?.item_count ?? 0) > 0;
  const sameSite = !!website && !!profile?.website && displayHost(website) === displayHost(profile.website);
  const scannedThisSite = sameSite && (status === "ready" || status === "limited") && hasKnowledge;
  const showReview = !!profile && !analyzing && (hasKnowledge || manual || status === "ready" || status === "limited" || status === "failed");

  async function analyze() {
    const url = normalizeUrl(website);
    if (!url) return;
    onChange({ website: url });
    setStarting(true);
    try {
      // Save what we know first so the analysis has context.
      await put<BusinessProfile>("/api/business-profile", {
        name: business.name ?? "",
        industry: business.industry ?? "",
        website: url,
        description: business.description ?? "",
      });
      const p = await post<BusinessProfile>("/api/business-profile/analyze", { website: url });
      onProfile(p);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setStarting(false);
    }
  }

  const industries = catalog?.industries ?? [];

  return (
    <div>
      {knowledgeOnly ? (
        <StepTitle
          title="What should your agent know?"
          description="Add your website and we'll help your agent learn about your business. You review everything before it's used."
        />
      ) : (
        <StepTitle title="Tell us about your business" description="We'll use this to write how your agent talks about you." />
      )}

      <div className="space-y-5">
        {!knowledgeOnly && (
          <>
        <Field label="Business name">
          <Input
            value={business.name ?? ""}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="e.g. Acme Heating & Air"
            autoComplete="organization"
            aria-invalid={showErrors && !business.name?.trim()}
            className={cn(showErrors && !business.name?.trim() && "border-red-300")}
          />
          {showErrors && !business.name?.trim() && <span className="mt-1 block text-xs text-red-600">Please enter your business name.</span>}
        </Field>

        <div>
          <span className="mb-1.5 block text-xs font-medium text-zinc-700">Industry</span>
          {!catalog ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-lg bg-zinc-100" />
              ))}
            </div>
          ) : (
            <div role="radiogroup" aria-label="Industry" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {industries.map((ind) => {
                const Icon = industryIcon(ind.icon, ind.key);
                const selected = business.industry === ind.key;
                return (
                  <button
                    key={ind.key}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => onChange({ industry: ind.key })}
                    className={cn(
                      "flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
                      selected
                        ? "border-brand-500 bg-brand-50/60 text-brand-800 ring-1 ring-brand-500"
                        : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50",
                    )}
                  >
                    <Icon className={cn("h-4 w-4 shrink-0", selected ? "text-brand-600" : "text-zinc-400")} />
                    <span className="truncate">{ind.label}</span>
                  </button>
                );
              })}
            </div>
          )}
          {showErrors && !business.industry && <span className="mt-1 block text-xs text-red-600">Please pick the closest match.</span>}
        </div>

        <Field label="Description (optional)" hint="A sentence or two about what you do and who you serve.">
          <VoiceTextarea
            rows={2}
            value={business.description ?? ""}
            onValue={(v) => onChange({ description: v })}
            placeholder="e.g. We install and repair heating and cooling systems for homes in Austin."
          />
        </Field>
          </>
        )}

        {/* Website + knowledge */}
        <div className="rounded-xl border border-zinc-200 bg-zinc-50/60 p-4">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg brand-gradient text-white">
              <Sparkles className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-zinc-900">{knowledgeOnly ? "Your website" : "Teach your agent about your business"}</h3>
              <p className="mt-0.5 text-xs text-zinc-500">
                Add your website and we&apos;ll pull out your services, hours, team and common questions. You&apos;ll review everything.
              </p>
            </div>
          </div>

          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Globe className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
              <Input
                aria-label="Website"
                type="url"
                inputMode="url"
                value={website}
                onChange={(e) => onChange({ website: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (!analyzing && website.trim()) analyze();
                  }
                }}
                placeholder="yourbusiness.com"
                className="pl-9"
                disabled={analyzing}
              />
            </div>
            {!scannedThisSite && (
              <Button variant="primary" onClick={analyze} loading={starting} disabled={!website.trim() || analyzing}>
                {!starting && <Sparkles className="h-4 w-4" />} Analyze website
              </Button>
            )}
          </div>

          {scannedThisSite && profile && !analyzing && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2.5 ring-1 ring-emerald-200">
              <p className="flex min-w-0 items-center gap-2 text-xs text-zinc-700">
                <Check className="h-4 w-4 shrink-0 text-emerald-600" />
                <span>
                  We already know about <span className="font-semibold">{profile.name || business.name || "your business"}</span> —{" "}
                  {profile.item_count} facts from {displayHost(profile.website)}
                </span>
              </p>
              <Button size="sm" variant="ghost" onClick={analyze} loading={starting}>
                {!starting && <RefreshCw className="h-3.5 w-3.5" />} Re-analyze
              </Button>
            </div>
          )}

          {analyzing && profile && <AnalysisProgress step={profile.progress_step} />}

          {profile && !analyzing && (status === "failed" || status === "limited") && profile.error && (
            <div className="mt-3">
              <Notice tone={status === "failed" ? "red" : "amber"}>
                <span className="flex gap-2">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    {profile.error} You can add details yourself below or upload a file — or continue without it.
                  </span>
                </span>
              </Notice>
            </div>
          )}

          {!showReview && !analyzing && (
            <button
              type="button"
              onClick={() => setManual(true)}
              className="mt-3 text-xs font-medium text-zinc-600 underline decoration-zinc-300 underline-offset-2 hover:text-zinc-900"
            >
              No website? Add details yourself or upload a file
            </button>
          )}
        </div>

        {showReview && profile && <KnowledgeReview profile={profile} onProfile={onProfile} />}
      </div>
    </div>
  );
}

function AnalysisProgress({ step }: { step: number | null }) {
  const current = step ?? 0;
  return (
    <ol className="mt-4 space-y-2.5" aria-live="polite">
      {STAGES.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex items-center gap-2.5 text-sm">
            <span
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors",
                done && "bg-emerald-500 text-white",
                active && "bg-brand-50 text-brand-600",
                !done && !active && "bg-zinc-100 text-zinc-300",
              )}
            >
              {done ? (
                <Check className="h-3 w-3" strokeWidth={3} />
              ) : active ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
              )}
            </span>
            <span className={cn(done ? "text-zinc-500" : active ? "font-medium text-zinc-900" : "text-zinc-400")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
