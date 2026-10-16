"use client";

import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  Clock,
  Phone,
  ShieldCheck,
  Globe,
  Loader2,
  User,
  UserSearch,
  Users,
  UsersRound,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import styles from "./onboarding.module.css";
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

const TEAM: { value: string; label: string; icon: typeof User }[] = [
  { value: "just_me", label: "Just me", icon: User },
  { value: "2_5", label: "2–5", icon: Users },
  { value: "6_20", label: "6–20", icon: UsersRound },
  { value: "21_plus", label: "21+", icon: Building2 },
];

const STEPS = ["Your business", "Industry", "Goals", "Contact"] as const;

/** Free-trial onboarding for a login that isn't in an account yet: a guided setup, then a workspace. */
export function Onboarding() {
  const router = useRouter();
  const { mutate } = useSession();
  const {
    data: opts,
    error: optsError,
    mutate: reloadOptions,
  } = useSWR<Options>("/api/onboarding/options", fetcher, {
    revalidateOnFocus: false,
  });
  const [step, setStep] = useState(0);
  const [company, setCompany] = useState("");
  const [team, setTeam] = useState<string | null>(null);
  const [website, setWebsite] = useState("");
  const [phone, setPhone] = useState("");
  const headingRef = useRef<HTMLDivElement>(null);
  const submitting = useRef(false);
  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);
  const [industry, setIndustry] = useState<string | null>(null);
  const [goals, setGoals] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const specialties = industry
    ? (opts?.specialties[industry] ?? opts?.specialties.other ?? [])
    : [];
  const leadFinder =
    !!industry && !!opts?.lead_finder_industries.includes(industry);
  const industryLabel = opts?.industries.find((i) => i.key === industry)?.label;
  const phoneDigits = phone.replace(/\D/g, "");
  const phoneValid = phone.trim().startsWith("+")
    ? /^[+][1-9][\d\s().-]*$/.test(phone.trim()) &&
      phoneDigits.length >= 8 &&
      phoneDigits.length <= 15
    : /^[\d\s().-]+$/.test(phone.trim()) &&
      (phoneDigits.length === 10 ||
        (phoneDigits.length === 11 && phoneDigits.startsWith("1")));
  const valid = [
    company.trim().length > 0,
    !!industry,
    goals.length > 0 || other.trim().length >= 3,
    phoneValid,
  ];

  function next() {
    if (saving || submitting.current) return;
    if (!valid[step]) return setShowErrors(true);
    setShowErrors(false);
    if (step < STEPS.length - 1) setStep(step + 1);
    else void finish();
  }

  async function finish() {
    if (submitting.current) return;
    submitting.current = true;
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
        phone: phone.trim(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      await mutate(s, false);
      router.replace("/dashboard?welcome=1");
    } catch (e) {
      setError(
        e instanceof ApiError || e instanceof Error
          ? e.message
          : "Something went wrong.",
      );
      submitting.current = false;
      setSaving(false);
    }
  }

  return (
    <main className={styles.stage}>
      <div className={styles.shell}>
        <section className={styles.story} aria-label="Your BlackSync workspace">
          <Logo className="text-white" />
          <div className={styles.storyBody}>
            <span className={styles.eyebrow}>
              A little setup. A running start.
            </span>
            <h2>
              Your next
              <br />
              conversation
              <br />
              <span>starts here.</span>
            </h2>
            <p>
              A workspace shaped around your business, your team, and what comes
              next.
            </p>
            <ol className={styles.roadmap}>
              {STEPS.map((label, i) => (
                <li
                  key={label}
                  aria-current={i === step ? "step" : undefined}
                  data-current={i === step}
                  data-complete={i < step}
                >
                  <span>{i < step ? <Check size={14} /> : `0${i + 1}`}</span>
                  <div>
                    {label}
                    <small>
                      {
                        [
                          "Make it yours",
                          "Find your fit",
                          "Choose your first win",
                          "Stay connected",
                        ][i]
                      }
                    </small>
                  </div>
                </li>
              ))}
            </ol>
          </div>
          <div className={styles.storyFoot}>
            <ShieldCheck size={15} /> No credit card needed to get started
          </div>
        </section>

        <section className={styles.questions}>
          <div className={styles.mobileBrand}>
            <Logo />
            <span className="text-xs text-zinc-500">Workspace setup</span>
          </div>
          <div className={styles.questionBody}>
            <div className={styles.topline}>
              <span>
                <Clock size={13} /> About a minute
              </span>
              <span>Made for your team</span>
            </div>
            {/* Progress */}
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-widest text-brand-600">
              Step {step + 1} of {STEPS.length}
            </div>
            <div
              className="mb-7 flex items-center gap-2"
              aria-label={`Step ${step + 1} of ${STEPS.length}`}
            >
              {STEPS.map((s, i) => (
                <div key={s} className="flex flex-1 flex-col gap-1.5">
                  <div
                    className={cn(
                      "h-1 rounded-full transition-colors duration-500",
                      i <= step ? "bg-brand-500" : "bg-zinc-200",
                    )}
                  />
                  <span
                    className={cn(
                      "text-[11px] font-medium",
                      i === step ? "text-zinc-900" : "text-zinc-400",
                    )}
                  >
                    {s}
                  </span>
                </div>
              ))}
            </div>

            {optsError && (
              <div
                role="alert"
                className="mb-5 rounded-xl bg-red-50 p-3 text-sm text-red-700"
              >
                We couldn&apos;t load your setup options.{" "}
                <button
                  type="button"
                  onClick={() => void reloadOptions()}
                  className="font-semibold underline"
                >
                  Try again
                </button>
              </div>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault();
                next();
              }}
              id="workspace-setup"
              noValidate
              aria-label={STEPS[step]}
            >
              <div
                key={step}
                ref={headingRef}
                tabIndex={-1}
                className={styles.step}
              >
                {step === 0 && (
                  <div className="space-y-6">
                    <Header
                      title="First, make it yours."
                      subtitle="Tell us a little about the business behind your next great conversation."
                    />
                    <Field label="Company name">
                      <Input
                        aria-label="Company name"
                        autoComplete="organization"
                        aria-invalid={showErrors && !valid[0]}
                        value={company}
                        onChange={(e) => setCompany(e.target.value)}
                        placeholder="e.g. Summit Realty"
                        maxLength={120}
                      />
                      {showErrors && !valid[0] && (
                        <span className="mt-1 block text-xs text-red-600">
                          Please enter your company name.
                        </span>
                      )}
                    </Field>
                    <div>
                      <span className="mb-1.5 block text-xs font-medium text-zinc-700">
                        How many people are on your team?
                      </span>
                      <div className="grid grid-cols-4 gap-2">
                        {TEAM.map((t) => (
                          <button
                            key={t.value}
                            type="button"
                            onClick={() => setTeam(t.value)}
                            aria-pressed={team === t.value}
                            className={cn(
                              "flex flex-col items-center justify-center gap-1 rounded-2xl border py-3 text-sm font-medium shadow-sm transition",
                              team === t.value
                                ? "border-brand-500 bg-brand-50 text-brand-800 ring-1 ring-brand-500"
                                : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300",
                            )}
                          >
                            <t.icon
                              className={cn(
                                "h-4 w-4",
                                team === t.value
                                  ? "text-brand-600"
                                  : "text-zinc-400",
                              )}
                            />
                            {t.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <Field label="Website (optional)">
                      <Input
                        aria-label="Website (optional)"
                        autoComplete="url"
                        value={website}
                        onChange={(e) => setWebsite(e.target.value)}
                        placeholder="yourbusiness.com"
                        inputMode="url"
                      />
                      <span className="mt-1.5 flex items-center gap-1.5 text-xs text-zinc-500">
                        <Globe className="h-3.5 w-3.5 text-brand-500" />{" "}
                        We&apos;ll read it to teach your agents about your
                        business.
                      </span>
                    </Field>
                  </div>
                )}

                {step === 1 && (
                  <div className="space-y-5">
                    <Header
                      title="What industry are you in?"
                      subtitle="We'll set up your agents and tools for it. You can still build anything."
                    />
                    {!opts ? (
                      optsError ? (
                        <p className="text-sm text-red-600">
                          {(optsError as Error).message}
                        </p>
                      ) : (
                        <div className="grid gap-2 sm:grid-cols-2">
                          {Array.from({ length: 8 }).map((_, i) => (
                            <div
                              key={i}
                              className="h-16 animate-pulse rounded-xl bg-zinc-100"
                            />
                          ))}
                        </div>
                      )
                    ) : (
                      <div
                        role="radiogroup"
                        aria-label="Industry"
                        className="grid gap-2 sm:grid-cols-2"
                      >
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
                                on
                                  ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500"
                                  : "border-zinc-200 bg-white hover:border-zinc-300",
                              )}
                            >
                              <span
                                className={cn(
                                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                                  on
                                    ? "bg-brand-600 text-white"
                                    : "bg-zinc-100 text-zinc-600",
                                )}
                              >
                                <Icon className="h-4 w-4" />
                              </span>
                              <span className="min-w-0">
                                <span className="block text-sm font-semibold text-zinc-900">
                                  {i.label}
                                </span>
                                <span className="mt-0.5 block text-xs text-zinc-500">
                                  {i.hint}
                                </span>
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                    {showErrors && !valid[1] && (
                      <span className="block text-xs text-red-600">
                        Pick the closest match.
                      </span>
                    )}
                  </div>
                )}

                {step === 2 && (
                  <div className="space-y-5">
                    <Header
                      title="What should your AI agents do first?"
                      subtitle="Pick everything that fits — we'll recommend agents for these on your dashboard."
                    />
                    <div className="flex flex-wrap gap-2">
                      {specialties.map((s) => {
                        const on = goals.includes(s.key);
                        return (
                          <button
                            key={s.key}
                            type="button"
                            role="checkbox"
                            aria-checked={on}
                            onClick={() =>
                              setGoals((g) =>
                                on
                                  ? g.filter((k) => k !== s.key)
                                  : [...g, s.key],
                              )
                            }
                            className={cn(
                              "inline-flex min-h-10 items-center gap-1.5 rounded-full border px-4 text-sm font-medium transition",
                              on
                                ? "border-brand-500 bg-brand-50 text-brand-800 ring-1 ring-brand-500"
                                : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300",
                            )}
                          >
                            {on && (
                              <Check className="h-3.5 w-3.5" strokeWidth={3} />
                            )}
                            {s.label}
                          </button>
                        );
                      })}
                    </div>
                    <Field
                      label={
                        specialties.length
                          ? "Anything else? (optional)"
                          : "What do you want AI calling for?"
                      }
                    >
                      <VoiceTextarea
                        rows={2}
                        value={other}
                        onValue={setOther}
                        placeholder="e.g. Call back missed calls and book estimates"
                      />
                    </Field>
                    {showErrors && !valid[2] && (
                      <span className="block text-xs text-red-600">
                        Pick at least one, or describe it in a few words.
                      </span>
                    )}
                    {leadFinder && (
                      <p className="flex items-start gap-2 rounded-xl bg-white p-3 text-xs text-zinc-600 ring-1 ring-zinc-900/[0.06]">
                        <UserSearch className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                        Your workspace includes Lead Finder: look up property
                        owners and their contact details, then call them with
                        your agents.
                      </p>
                    )}
                  </div>
                )}
                {step === 3 && (
                  <div className="space-y-6">
                    <div className={styles.phoneIcon}>
                      <Phone size={24} />
                    </div>
                    <Header
                      title="One last thing. Stay connected."
                      subtitle="What's the best number to reach you? We'll save it with your account so our team can help you get started."
                    />
                    <Field label="Your phone number">
                      <Input
                        type="tel"
                        inputMode="tel"
                        autoComplete="tel"
                        aria-label="Your phone number"
                        aria-required="true"
                        aria-invalid={showErrors && !phoneValid}
                        aria-describedby="phone-hint phone-error"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        placeholder="(415) 555-0123"
                        maxLength={40}
                        className="text-lg!"
                      />
                      <p
                        id="phone-hint"
                        className="mt-2 text-xs leading-relaxed text-zinc-500"
                      >
                        US or Canada: enter your 10-digit number. Elsewhere:
                        include the country code, like +44.
                      </p>
                      <p
                        id="phone-error"
                        role="alert"
                        className="mt-1 text-xs text-red-600"
                      >
                        {showErrors && !phoneValid
                          ? "Enter a valid phone number, including the country code if outside the US or Canada."
                          : ""}
                      </p>
                    </Field>
                    <div className={styles.summary}>
                      <span className={styles.eyebrow}>
                        Your workspace, ready to go
                      </span>
                      <strong>{company}</strong>
                      <p>
                        {industryLabel} ·{" "}
                        {TEAM.find((t) => t.value === team)?.label ??
                          "Your team"}
                      </p>
                      <span>
                        <Check size={14} /> {opts?.trial_credits ?? 30} calling
                        credits included
                      </span>
                    </div>
                    <p className="flex items-start gap-2 text-xs leading-relaxed text-zinc-500">
                      <ShieldCheck size={15} className="mt-0.5 shrink-0" /> This
                      saves your contact number. You can configure live call
                      transfers later in your agent settings.
                    </p>
                  </div>
                )}
              </div>
              {error && (
                <p
                  role="alert"
                  className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700"
                >
                  {error}
                </p>
              )}
            </form>

            <div className={styles.navigation}>
              {step > 0 ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setShowErrors(false);
                    setError("");
                    setStep(step - 1);
                  }}
                  disabled={saving}
                >
                  <ArrowLeft className="h-4 w-4" /> Back
                </Button>
              ) : (
                <button
                  type="button"
                  onClick={signOut}
                  className="max-w-[45%] text-left text-xs leading-snug text-zinc-500 hover:text-zinc-800"
                >
                  Have an invite?{" "}
                  <span className="underline underline-offset-2">
                    Use a different login
                  </span>
                </button>
              )}
              <Button
                type="submit"
                form="workspace-setup"
                variant="primary"
                className={styles.continue}
                disabled={saving || !opts || !!optsError}
              >
                {saving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Setting up your
                    workspace…
                  </>
                ) : step === STEPS.length - 1 ? (
                  <>
                    Launch my workspace <ArrowRight className="h-4 w-4" />
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
      </div>
    </main>
  );
}

function Header({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <h1 className="font-display text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl">
        {title}
      </h1>
      <p className="mt-1.5 text-sm text-zinc-500">{subtitle}</p>
    </div>
  );
}
