"use client";

import { ArrowLeft, CalendarCheck, CheckCircle2, PhoneCall, Rocket, Wrench } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Card, Spinner } from "@/components/ui";
import { displayName, useSession } from "@/lib/session";

// Cal.com inline embed (event "onboarding-call").
const CAL_ORIGIN = "https://app.cal.com";
const CAL_LINK = "hamza-basal-v1hqkl/onboarding-call";
const NAMESPACE = "onboarding-call";
const EMBED_ID = "my-cal-inline-onboarding-call";

type CalFn = ((...args: unknown[]) => void) & { loaded?: boolean; ns: Record<string, (...args: unknown[]) => void>; q: unknown[][]; config?: Record<string, unknown> };

/** Cal.com's official loader snippet, unchanged in behavior. */
function loadCal(): CalFn {
  const w = window as unknown as { Cal?: CalFn };
  (function (C: typeof w, A: string, L: string) {
    const p = (a: { q: unknown[] }, ar: unknown) => a.q.push(ar);
    const d = document;
    C.Cal =
      C.Cal ||
      (function (this: unknown, ...ar: unknown[]) {
        const cal = C.Cal!;
        if (!cal.loaded) {
          cal.ns = {};
          cal.q = cal.q || [];
          d.head.appendChild(d.createElement("script")).src = A;
          cal.loaded = true;
        }
        if (ar[0] === L) {
          const api = function (...a: unknown[]) {
            p(api as unknown as { q: unknown[] }, a);
          } as unknown as { q: unknown[] };
          const namespace = ar[1];
          api.q = api.q || [];
          if (typeof namespace === "string") {
            cal.ns[namespace] = cal.ns[namespace] || (api as unknown as CalFn);
            p(cal.ns[namespace] as unknown as { q: unknown[] }, ar);
            p(cal as unknown as { q: unknown[] }, ["initNamespace", namespace]);
          } else p(cal as unknown as { q: unknown[] }, ar);
          return;
        }
        p(cal as unknown as { q: unknown[] }, ar);
      } as CalFn);
  })(w, `${CAL_ORIGIN}/embed/embed.js`, "init");
  return w.Cal!;
}

const STEPS = [
  { icon: PhoneCall, title: "A quick 15-minute call", text: "Tell us about your business, your leads and what a great call sounds like." },
  { icon: Wrench, title: "We build it for you", text: "Script, voice, knowledge, booking and transfers — set up and tested by our team." },
  { icon: Rocket, title: "Launch together", text: "We walk you through it, run test calls and go live when you're happy." },
];

export default function ExpertBuildPage() {
  const { session, loading } = useSession();
  const started = useRef(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (started.current || loading) return;
    started.current = true;
    const Cal = loadCal();
    Cal("init", NAMESPACE, { origin: CAL_ORIGIN });
    Cal.config = Cal.config || {};
    Cal.config.forwardQueryParams = true;
    const u = session?.user;
    Cal.ns[NAMESPACE]("inline", {
      elementOrSelector: `#${EMBED_ID}`,
      config: {
        layout: "month_view",
        useSlotsViewOnSmallScreen: "true",
        // Prefill who's booking (they can still edit it on the form).
        ...(u ? { name: displayName(u), email: u.email } : {}),
        ...(session?.org?.name ? { notes: `Account: ${session.org.name}` } : {}),
      },
      calLink: CAL_LINK,
    });
    Cal.ns[NAMESPACE]("ui", { hideEventTypeDetails: false, layout: "month_view", cssVarsPerTheme: { light: { "cal-brand": "#E5531F" } } });
    Cal.ns[NAMESPACE]("on", { action: "linkReady", callback: () => setReady(true) });
    const t = setTimeout(() => setReady(true), 6000); // never leave the spinner up forever
    return () => clearTimeout(t);
    // Created once, after the session loads (so name and email can be prefilled).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  return (
    <div className="mx-auto max-w-5xl">
      <Link href="/agents" className="mb-4 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900">
        <ArrowLeft className="h-4 w-4" /> Agents
      </Link>
      <div className="mb-6 max-w-2xl">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-white">
          Done for you
        </span>
        <h1 className="mt-3 font-display text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl">Have an expert build your agent</h1>
        <p className="mt-2 text-sm text-zinc-600">
          Book a call with the BlackSync team. We&apos;ll design, build and test your AI calling agent around your business — you just show up.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
        <ol className="flex flex-col gap-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3 rounded-2xl bg-white p-4 ring-1 ring-zinc-900/[0.06]">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600">
                <s.icon className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-zinc-900">
                  <span className="mr-1 text-zinc-400">{i + 1}.</span>
                  {s.title}
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">{s.text}</p>
              </div>
            </li>
          ))}
          <li className="flex items-start gap-2 px-1 pt-1 text-xs text-zinc-500">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
            Prefer to try it yourself first? <Link href="/agents/new" className="font-medium text-brand-700 hover:text-brand-800">Build with AI</Link>
          </li>
        </ol>

        <Card className="relative min-h-[560px] p-0">
          {!ready && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-sm text-zinc-500">
              <Spinner />
              <span className="flex items-center gap-1.5">
                <CalendarCheck className="h-4 w-4" /> Loading available times…
              </span>
            </div>
          )}
          {/* Cal sizes its iframe to the calendar's height. */}
          <div id={EMBED_ID} style={{ width: "100%", overflow: "auto" }} className="rounded-2xl" />
        </Card>
      </div>
    </div>
  );
}
