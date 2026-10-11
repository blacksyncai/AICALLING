"use client";

import { UserButton } from "@clerk/nextjs";
import { ArrowLeft, ArrowRight, Check, Coins, Headphones, Loader2, Sparkles, UserSearch } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { Logo } from "@/components/Logo";
import { VoiceTextarea } from "@/components/MicButton";
import { industryIcon } from "@/components/builder/parts";
import { Button, Field, Input } from "@/components/ui";
import { ApiError, fetcher, post } from "@/lib/api";
import { signOut, useSession } from "@/lib/session";
import type { Session } from "@/lib/types";
import { cn } from "@/lib/utils";

type Options = {
  industries: { key: string; label: string; icon: string; hint: string }[];
  specialties: Record<string, { key: string; label: string }[]>;
  lead_finder_industries: string[];
  trial_credits: number;
};

const TEAM: { value: string; label: string }[] = [
  { value: "just_me", label: "Just me" },
  { value: "2_5", label: "2–5" },
  { value: "6_20", label: "6–20" },
  { value: "21_plus", label: "21+" },
];

const STEPS = ["Your business", "Industry", "Goals"] as const;

/** Free-trial onboarding for a login that isn't in an account yet: three questions, then a workspace. */
export function Onboarding() {
  const router = useRouter();
  const { session, mutate } = useSession();
  const { data: opts, error: optsError } = useSWR<Options>("/api/onboarding/options", fetcher, { revalidateOnFocus: false });
  const [step, setStep] = useState(0);
  const [company, setCompany] = useState("");
  const [team, setTeam] = useState<string | null>(null);
  const [website, setWebsite] = useState("");
  const [industry, setIndustry] = useState<string | null>(null);
  const [goals, setGoals] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const specialties = industry ? opts?.specialties[industry] ?? opts?.specialties.other ?? [] : [];
  const leadFinder = !!industry && !!opts?.lead_finder_industries.includes(industry);
  const industryLabel = opts?.industries.find((i) => i.key === industry)?.label;
  const valid = [company.trim().length > 0, !!industry, goals.length > 0 || other.trim().length >= 3];

  function next() {
    if (!valid[step]) return setShowErrors(true);
    setShowErrors(false);
    if (step < STEPS.length - 1) setStep(step + 1);
    else void finish();
  }

  async function finish() {
    setSaving(true);
    setError("");
    try {
      const s = await post<Session>("/api/onboarding/start", {
        company: company.trim(),
        industry,
        goals,
        other_goal: other.trim(),
        team_size: team,
        website: website.trim(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      await mutate(s, false);
      router.replace("/dashboard?welcome=1");
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong.");
      setSaving(false);
    }
  }

  const includes = [
    { icon: Coins, text: `${opts?.trial_credits ?? 30} free calling credits — no card needed`, on: true },
    { icon: Headphones, text: "Marissa, a demo agent you can talk to right away", on: true },
    { icon: Sparkles, text: industryLabel ? `Build with AI, set up for ${industryLabel}` : "Build with AI, set up for your industry", on: !!industry },
    { icon: UserSearch, text: "Lead Finder — look up property owners", on: leadFinder },
  ];

  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      {/* What they get, updating as they answer */}
      <section className="relative hidden overflow-hidden bg-zinc-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(700px_420px_at_10%_0%,rgba(236,101,60,0.28),transparent_65%),radial-gradient(600px_400px_at_100%_100%,rgba(245,158,11,0.12),transparent_70%)]" />
        <div className="relative">
          <Logo className="text-white" />
        </div>
        <div className="relative max-w-md">
          <p className="text-xs font-semibold uppercase tracking-widest text-brand-400">Free trial</p>
          <h2 className="mt-3 font-display text-4xl font-semibold leading-[1.1] tracking-tight">Let&apos;s set up your workspace.</h2>
          <p className="mt-3 text-sm text-zinc-400">Three quick questions and we&apos;ll tailor BlackSync to how you sell.</p>
          <ul className="mt-10 space-y-4">
            {includes.map(({ icon: Icon, text, on }) => (
              <li key={text} className={cn("flex items-center gap-3 transition-opacity duration-500", on ? "opacity-100" : "opacity-35")}>
                <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset", on ? "bg-brand-500/15 ring-brand-400/30" : "bg-white/[0.04] ring-white/10")}>
                  <Icon className={cn("h-4 w-4", on ? "text-brand-400" : "text-zinc-500")} />
                </span>
                <span className="text-sm">{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="relative flex items-center gap-3 text-xs text-zinc-500">
          <UserButton />
          <span className="truncate">Signed in as {session?.user.email}</span>
        </div>
      </section>

      <section className="app-canvas flex flex-col px-4 py-8 sm:px-10">
        <div className="flex items-center justify-between lg:hidden">
          <Logo />
          <UserButton />
        </div>
        <div className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center py-8">
          {/* Progress */}
          <div className="mb-8 flex items-center gap-2" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
            {STEPS.map((s, i) => (
              <div key={s} className="flex flex-1 flex-col gap-1.5">
                <div className={cn("h-1 rounded-full transition-colors duration-500", i <= step ? "bg-brand-500" : "bg-zinc-200")} />
                <span className={cn("text-[11px] font-medium", i === step ? "text-zinc-900" : "text-zinc-400")}>{s}</span>
              </div>
            ))}
          </div>

          <div key={step} className="transition duration-300 ease-out starting:translate-y-2 starting:opacity-0">
            {step === 0 && (
              <div className="space-y-6">
                <Header title="Welcome to BlackSync" subtitle="First, tell us a little about your business." />
                <Field label="Company name">
                  <Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="e.g. Summit Realty" autoFocus maxLength={120} />
                  {showErrors && !valid[0] && <span className="mt-1 block text-xs text-red-600">Please enter your company name.</span>}
                </Field>
                <div>
                  <span className="mb-1.5 block text-xs font-medium text-zinc-700">How many people are on your team?</span>
                  <div className="grid grid-cols-4 gap-2">
                    {TEAM.map((t) => (
                      <button
                        key={t.value}
                        type="button"
                        onClick={() => setTeam(t.value)}
                        aria-pressed={team === t.value}
                        className={cn(
                          "h-10 rounded-xl border text-sm font-medium transition",
                          team === t.value ? "border-brand-500 bg-brand-50 text-brand-800 ring-1 ring-brand-500" : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300",
                        )}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>
                <Field label="Website (optional)" hint="We can read it later to teach your agents about your business.">
                  <Input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="yourbusiness.com" inputMode="url" />
                </Field>
              </div>
            )}

            {step === 1 && (
              <div className="space-y-5">
                <Header title="What industry are you in?" subtitle="We'll set up your agents and tools for it. You can still build anything." />
                {!opts ? (
                  optsError ? (
                    <p className="text-sm text-red-600">{(optsError as Error).message}</p>
                  ) : (
                    <div className="grid gap-2 sm:grid-cols-2">
                      {Array.from({ length: 8 }).map((_, i) => (
                        <div key={i} className="h-16 animate-pulse rounded-xl bg-zinc-100" />
                      ))}
                    </div>
                  )
                ) : (
                  <div role="radiogroup" aria-label="Industry" className="grid gap-2 sm:grid-cols-2">
                    {opts.industries.map((i) => {
                      const Icon = industryIcon(i.icon, i.key);
                      const on = industry === i.key;
                      return (
                        <button
                          key={i.key}
                          type="button"
                          role="radio"
                          aria-checked={on}
                          onClick={() => {
                            if (industry !== i.key) setGoals([]);
                            setIndustry(i.key);
                          }}
                          className={cn(
                            "flex items-start gap-3 rounded-xl border p-3 text-left transition",
                            on ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-zinc-200 bg-white hover:border-zinc-300",
                          )}
                        >
                          <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", on ? "bg-brand-600 text-white" : "bg-zinc-100 text-zinc-600")}>
                            <Icon className="h-4 w-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-sm font-semibold text-zinc-900">{i.label}</span>
                            <span className="mt-0.5 block text-xs text-zinc-500">{i.hint}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {showErrors && !valid[1] && <span className="block text-xs text-red-600">Pick the closest match.</span>}
              </div>
            )}

            {step === 2 && (
              <div className="space-y-5">
                <Header title="What should your AI agents do first?" subtitle="Pick everything that fits — we'll recommend agents for these on your dashboard." />
                <div className="flex flex-wrap gap-2">
                  {specialties.map((s) => {
                    const on = goals.includes(s.key);
                    return (
                      <button
                        key={s.key}
                        type="button"
                        role="checkbox"
                        aria-checked={on}
                        onClick={() => setGoals((g) => (on ? g.filter((k) => k !== s.key) : [...g, s.key]))}
                        className={cn(
                          "inline-flex min-h-10 items-center gap-1.5 rounded-full border px-4 text-sm font-medium transition",
                          on ? "border-brand-500 bg-brand-50 text-brand-800 ring-1 ring-brand-500" : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300",
                        )}
                      >
                        {on && <Check className="h-3.5 w-3.5" strokeWidth={3} />}
                        {s.label}
                      </button>
                    );
                  })}
                </div>
                <Field label={specialties.length ? "Anything else? (optional)" : "What do you want AI calling for?"}>
                  <VoiceTextarea rows={2} value={other} onValue={setOther} placeholder="e.g. Call back missed calls and book estimates" />
                </Field>
                {showErrors && !valid[2] && <span className="block text-xs text-red-600">Pick at least one, or describe it in a few words.</span>}
                {leadFinder && (
                  <p className="flex items-start gap-2 rounded-xl bg-white p-3 text-xs text-zinc-600 ring-1 ring-zinc-900/[0.06]">
                    <UserSearch className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                    Your workspace includes Lead Finder: look up property owners and their contact details, then call them with your agents.
                  </p>
                )}
                {error && <p className="text-sm text-red-600">{error}</p>}
              </div>
            )}
          </div>

          <div className="mt-8 flex items-center justify-between gap-3">
            {step > 0 ? (
              <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={saving}>
                <ArrowLeft className="h-4 w-4" /> Back
              </Button>
            ) : (
              <button type="button" onClick={signOut} className="text-xs text-zinc-500 hover:text-zinc-800">
                Have an invite instead? Use a different login
              </button>
            )}
            <Button variant="primary" className="rounded-full! px-6" onClick={next} disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Setting up your workspace…
                </>
              ) : step === STEPS.length - 1 ? (
                <>
                  Start my free trial <ArrowRight className="h-4 w-4" />
                </>
              ) : (
                <>
                  Continue <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </div>
        </div>
      </section>
    </main>
  );
}

function Header({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <h1 className="font-display text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl">{title}</h1>
      <p className="mt-1.5 text-sm text-zinc-500">{subtitle}</p>
    </div>
  );
}
