"use client";

import {
  ArrowRight, Bot, CalendarClock, Check, Database, FileSpreadsheet, Flame, Home, Lock, Plug, Radar as RadarIcon, RotateCcw,
  Save, Search, Sparkles, Tag, UserX, Users,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Modal } from "@/components/ui";
import { cn } from "@/lib/utils";

// Everything here is a client-side demonstration with fictional sample data. It never calls the
// Radar API and never connects to or reads anyone's CRM.

type Step = "intro" | "pick" | "scanning" | "results";

const CRMS = [
  { key: "fub", name: "Follow Up Boss", scale: 1, icon: Users },
  { key: "ghl", name: "GoHighLevel", scale: 0.86, icon: Flame },
  { key: "salesforce", name: "Salesforce", scale: 1.7, icon: Database },
  { key: "hubspot", name: "HubSpot", scale: 1.25, icon: Tag },
  { key: "csv", name: "CSV / Spreadsheet", scale: 0.55, icon: FileSpreadsheet },
  { key: "other", name: "Other CRM", scale: 0.9, icon: Plug },
] as const;
type Crm = (typeof CRMS)[number];

const STAGES = [
  "Reviewing lead activity",
  "Identifying follow-up gaps",
  "Finding older opportunities",
  "Grouping leads by potential next action",
  "Preparing opportunity summary",
];

const BASE = { analyzed: 1240, followUp: 186, stale: 312, buyers: 74, sellers: 41, reactivate: 96 };

const CATEGORIES = [
  { key: "priority", title: "High-Priority Follow-Up", icon: Flame, count: (s: typeof BASE) => s.followUp,
    blurb: "Leads who previously showed interest but appear to have missed subsequent follow-up." },
  { key: "reactivation", title: "Database Reactivation", icon: RotateCcw, count: (s: typeof BASE) => s.reactivate,
    blurb: "Older contacts who could be worth reconnecting with." },
  { key: "buyers", title: "Buyer Opportunities", icon: Search, count: (s: typeof BASE) => s.buyers,
    blurb: "Previous buyer inquiries that may benefit from renewed outreach." },
  { key: "sellers", title: "Seller Opportunities", icon: Home, count: (s: typeof BASE) => s.sellers,
    blurb: "Previous seller inquiries with potential follow-up value." },
  { key: "unworked", title: "Unworked Leads", icon: UserX, count: (s: typeof BASE) => s.stale,
    blurb: "Records that have not received appropriate follow-up." },
] as const;
type CategoryKey = (typeof CATEGORIES)[number]["key"];

interface SampleLead {
  name: string;
  activity: string;
  opportunity: string;
  next: string;
  ai: string;
}

// Fictional people and fictional activity.
const LEADS: Record<CategoryKey, SampleLead[]> = {
  priority: [
    { name: "Jordan Ellis", activity: "Asked for a callback through a web form 9 days ago; no call logged since.",
      opportunity: "Requested contact and may still be waiting to hear back.", next: "Call to follow up on the original request.",
      ai: "“Hi Jordan, this is Ava with Maple Realty — you'd asked us to call you back. Is now still a good time?”" },
    { name: "Priya Nair", activity: "Opened 3 listing emails last week; last conversation 41 days ago.",
      opportunity: "Recent engagement after a long gap.", next: "Check in and confirm what she's looking for now.",
      ai: "Short check-in call offering updated listings in her saved area." },
    { name: "Marcus Webb", activity: "Booked a showing in March, then no further notes.",
      opportunity: "A past showing with no recorded outcome.", next: "Ask how the search is going.",
      ai: "Friendly call asking whether he's still looking and offering a new showing." },
  ],
  reactivation: [
    { name: "Elena Ruiz", activity: "Last contacted 14 months ago; tagged “nurture”.",
      opportunity: "An older contact who may be worth reconnecting with.", next: "A light-touch reconnect call.",
      ai: "“Hi Elena, it's been a while — wanted to see if anything has changed with your plans.”" },
    { name: "Tom Becker", activity: "Closed a purchase 4 years ago; no contact since.",
      opportunity: "Past clients sometimes refer or move again.", next: "Anniversary check-in.",
      ai: "Home-anniversary call offering a free value update." },
    { name: "Grace Okafor", activity: "Unsubscribed from emails 2 years ago; phone still on file.",
      opportunity: "Phone may be the only channel left.", next: "Verify consent before calling.",
      ai: "Only after consent is confirmed: a brief, respectful reconnect call." },
  ],
  buyers: [
    { name: "Sam Patel", activity: "Pre-approval inquiry 6 months ago; marked “not ready”.",
      opportunity: "Timing may have changed.", next: "Ask about timeline and budget.",
      ai: "Call to ask whether the move is closer and offer a buyer consult." },
    { name: "Alicia Moreno", activity: "Viewed 12 listings in one neighborhood; never spoke with an agent.",
      opportunity: "Repeated interest in one area.", next: "Offer a neighborhood overview.",
      ai: "Call sharing two new listings in that neighborhood." },
  ],
  sellers: [
    { name: "Derek Hale", activity: "Requested a home valuation 5 months ago.",
      opportunity: "Valuation requests often come before a listing decision.", next: "Offer an updated valuation.",
      ai: "Call offering a refreshed valuation and a quick market update." },
    { name: "Nina Volkova", activity: "Expired listing with another brokerage in the spring.",
      opportunity: "May still want to sell.", next: "Ask what would make a relaunch worth it.",
      ai: "Consultative call about what changed and next steps." },
  ],
  unworked: [
    { name: "Chris Lambert", activity: "New lead from a portal 23 days ago; no calls, texts or emails logged.",
      opportunity: "Never contacted.", next: "First call introducing your team.",
      ai: "Speed-to-lead style intro call and a question about their goals." },
    { name: "Hannah Brooks", activity: "Imported in a batch 2 months ago; owner unassigned.",
      opportunity: "Fell through the cracks during import.", next: "Assign an owner and make first contact.",
      ai: "Intro call that qualifies interest and books a time with an agent." },
    { name: "Omar Haddad", activity: "Two missed inbound calls last month; no callback logged.",
      opportunity: "Tried to reach you.", next: "Call back and apologize for the delay.",
      ai: "“Hi Omar, we saw we missed your calls — how can we help?”" },
  ],
};

function stats(crm: Crm) {
  if (crm.key === "fub") return BASE;
  return Object.fromEntries(Object.entries(BASE).map(([k, v]) => [k, Math.round(v * crm.scale)])) as typeof BASE;
}

/** Radar sweep — decorative. */
function Sweep({ size = 160, active = true }: { size?: number; active?: boolean }) {
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      {[1, 0.7, 0.4].map((r) => (
        <div key={r} className="absolute rounded-full border border-brand-500/25" style={{ inset: `${((1 - r) / 2) * 100}%` }} />
      ))}
      <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle,rgba(249,115,22,0.18),transparent_65%)]" />
      {active && (
        <motion.div
          className="absolute inset-0 rounded-full"
          style={{ background: "conic-gradient(from 0deg, rgba(249,115,22,0.55), rgba(249,115,22,0) 70deg, transparent 360deg)" }}
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, ease: "linear", duration: 2.4 }}
        />
      )}
      {[[28, 34], [64, 22], [72, 66], [38, 70]].map(([x, y], i) => (
        <motion.span
          key={i}
          className="absolute h-2 w-2 rounded-full bg-brand-400 shadow-[0_0_10px_rgba(249,115,22,0.9)]"
          style={{ left: `${x}%`, top: `${y}%` }}
          animate={{ opacity: [0.2, 1, 0.2] }}
          transition={{ repeat: Infinity, duration: 2.4, delay: i * 0.6 }}
        />
      ))}
      <div className="absolute inset-0 flex items-center justify-center">
        <RadarIcon className="h-6 w-6 text-brand-400" />
      </div>
    </div>
  );
}

function DemoBadge({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full bg-amber-400/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-amber-600 ring-1 ring-amber-500/30", className)}>
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> Demo Mode — Sample Data
    </span>
  );
}

function UnlockModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Unlock the full power of Radar">
      <div className="space-y-4 text-sm text-zinc-900">
        <div className="flex gap-3 rounded-xl bg-zinc-950 p-4 text-zinc-200">
          <Sweep size={56} />
          <p>Connect your real CRM, uncover follow-up opportunities, and turn your existing lead database into actionable AI calling campaigns.</p>
        </div>
        <p className="text-xs text-zinc-500">Radar is included with Growth, Teams and Managed.</p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="h-10 rounded-full px-4 text-zinc-600 hover:bg-zinc-100">Maybe Later</button>
          <Link href="/billing?tab=plans&plan=growth" className="inline-flex h-10 items-center gap-1.5 rounded-full bg-gradient-to-t from-brand-600 to-brand-500 px-5 font-semibold text-white shadow-sm shadow-brand-500/30">
            View Plans <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </Modal>
  );
}

function LockedButton({ children, onClick, primary }: { children: React.ReactNode; onClick: () => void; primary?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-xs font-semibold transition active:scale-[0.98]",
        primary ? "bg-gradient-to-t from-brand-600 to-brand-500 text-white shadow-sm shadow-brand-500/30" : "bg-white text-zinc-800 ring-1 ring-zinc-900/10 hover:bg-zinc-50",
      )}
    >
      <Lock className="h-3 w-3 opacity-70" /> {children}
    </button>
  );
}

/** Radar for accounts whose plan doesn't include it: an intro and a clearly simulated scan. */
export function RadarPreview() {
  const [step, setStep] = useState<Step>("intro");
  const [crm, setCrm] = useState<Crm | null>(null);
  const [stage, setStage] = useState(0);
  const [cat, setCat] = useState<CategoryKey>("priority");
  const [locked, setLocked] = useState(false);
  const lock = () => setLocked(true);

  useEffect(() => {
    if (step !== "scanning") return;
    setStage(0);
    const timers = STAGES.map((_, i) => setTimeout(() => setStage(i + 1), 650 * (i + 1)));
    const done = setTimeout(() => setStep("results"), 650 * STAGES.length + 450);
    return () => [...timers, done].forEach(clearTimeout);
  }, [step]);

  const s = crm ? stats(crm) : BASE;
  const category = CATEGORIES.find((c) => c.key === cat)!;

  return (
    <div className="mx-auto max-w-6xl">
      <AnimatePresence mode="wait">
        {step === "intro" && (
          <motion.section key="intro" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
            className="relative overflow-hidden rounded-3xl bg-zinc-950 p-8 text-white ring-1 ring-brand-500/30 sm:p-12">
            <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-brand-500/25 blur-3xl" />
            <div className="relative flex flex-col items-start gap-10 md:flex-row md:items-center">
              <div className="max-w-xl">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-brand-300 ring-1 ring-white/15">
                  <Sparkles className="h-3 w-3" /> Radar · Growth plan and up
                </span>
                <h1 className="mt-4 font-display text-3xl font-semibold tracking-tight sm:text-4xl">Find the opportunities hiding in your CRM.</h1>
                <p className="mt-3 text-[15px] leading-relaxed text-zinc-300">
                  Radar helps uncover leads worth reconnecting with, identifies overlooked follow-up opportunities, and shows where your next conversations could come from.
                </p>
                <div className="mt-7 flex flex-wrap gap-3">
                  <button type="button" onClick={() => setStep("pick")}
                    className="inline-flex h-11 items-center gap-2 rounded-full bg-gradient-to-t from-brand-600 to-brand-500 px-6 text-sm font-semibold text-white shadow-lg shadow-brand-500/30 transition active:scale-[0.98]">
                    <RadarIcon className="h-4 w-4" /> Try Quick Scan
                  </button>
                  <Link href="/billing?tab=plans&plan=growth"
                    className="inline-flex h-11 items-center gap-2 rounded-full bg-white/10 px-6 text-sm font-semibold text-white ring-1 ring-white/20 hover:bg-white/15">
                    Upgrade to Unlock Radar <ArrowRight className="h-4 w-4" />
                  </Link>
                </div>
                <p className="mt-4 text-xs text-zinc-500">The quick scan is a demo with sample data — it doesn&apos;t connect to or read your CRM.</p>
              </div>
              <div className="mx-auto md:ml-auto"><Sweep size={220} /></div>
            </div>
          </motion.section>
        )}

        {step === "pick" && (
          <motion.section key="pick" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
            className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-zinc-900/[0.06] sm:p-10">
            <DemoBadge />
            <h2 className="mt-4 font-display text-2xl font-semibold tracking-tight text-zinc-900">Where are your leads stored?</h2>
            <p className="mt-1 text-sm text-zinc-500">We use this to tailor the demo. Nothing is connected and no records are read.</p>
            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {CRMS.map((c) => (
                <button key={c.key} type="button" onClick={() => setCrm(c)}
                  className={cn("flex items-center gap-3 rounded-2xl p-4 text-left text-sm font-medium ring-1 transition",
                    crm?.key === c.key ? "bg-brand-50 text-brand-800 ring-2 ring-brand-500" : "bg-white text-zinc-800 ring-zinc-900/10 hover:bg-zinc-50")}>
                  <span className={cn("flex h-9 w-9 items-center justify-center rounded-xl", crm?.key === c.key ? "bg-brand-500 text-white" : "bg-zinc-100 text-zinc-600")}>
                    <c.icon className="h-4 w-4" />
                  </span>
                  {c.name}
                  {crm?.key === c.key && <Check className="ml-auto h-4 w-4 text-brand-600" />}
                </button>
              ))}
            </div>
            <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
              <button type="button" onClick={() => setStep("intro")} className="text-sm text-zinc-500 hover:text-zinc-900">Back</button>
              <button type="button" disabled={!crm} onClick={() => setStep("scanning")}
                className="inline-flex h-11 items-center gap-2 rounded-full bg-zinc-900 px-6 text-sm font-semibold text-white transition hover:bg-zinc-800 disabled:opacity-40">
                Run Demo Scan <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </motion.section>
        )}

        {step === "scanning" && crm && (
          <motion.section key="scan" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="relative overflow-hidden rounded-3xl bg-zinc-950 p-8 text-white ring-1 ring-brand-500/30 sm:p-12">
            <div className="flex flex-col items-center gap-8 md:flex-row">
              <Sweep size={200} />
              <div className="w-full max-w-md">
                <DemoBadge className="text-amber-300" />
                <h2 className="mt-3 text-xl font-semibold">Running a demo scan for {crm.name}…</h2>
                <ol className="mt-5 space-y-3">
                  {STAGES.map((label, i) => (
                    <li key={label} className={cn("flex items-center gap-3 text-sm transition-colors", i < stage ? "text-zinc-200" : i === stage ? "text-white" : "text-zinc-600")}>
                      <span className={cn("flex h-5 w-5 items-center justify-center rounded-full ring-1",
                        i < stage ? "bg-brand-500 ring-brand-500" : i === stage ? "ring-brand-400" : "ring-zinc-700")}>
                        {i < stage ? <Check className="h-3 w-3" /> : i === stage ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400" /> : null}
                      </span>
                      {label}
                    </li>
                  ))}
                </ol>
                <div className="mt-6 h-1.5 overflow-hidden rounded-full bg-white/10">
                  <motion.div className="h-full rounded-full bg-brand-500" animate={{ width: `${(stage / STAGES.length) * 100}%` }} />
                </div>
              </div>
            </div>
          </motion.section>
        )}

        {step === "results" && crm && (
          <motion.section key="results" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-amber-50 px-4 py-3 ring-1 ring-amber-200">
              <div className="flex flex-wrap items-center gap-3">
                <DemoBadge />
                <span className="text-sm text-amber-900">
                  Fictional sample data showing what Radar could look like for a {crm.name} account. This is not an analysis of your account.
                </span>
              </div>
              <button type="button" onClick={() => { setStep("pick"); setCat("priority"); }} className="text-xs font-medium text-amber-900 underline">Try another CRM</button>
            </div>

            <div className="rounded-3xl bg-zinc-950 p-6 text-white ring-1 ring-brand-500/30 sm:p-8">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-widest text-zinc-500">Radar opportunity summary · sample</div>
                  <h2 className="mt-1 text-2xl font-semibold">CRM: {crm.name}</h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  <LockedButton onClick={lock}><Save className="h-3.5 w-3.5" /> Save scan</LockedButton>
                  <LockedButton onClick={lock}><CalendarClock className="h-3.5 w-3.5" /> Schedule scans</LockedButton>
                  <LockedButton onClick={lock}><Plug className="h-3.5 w-3.5" /> Connect my real CRM</LockedButton>
                </div>
              </div>
              <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                {[
                  ["Demo leads analyzed", s.analyzed], ["Potential follow-up opportunities", s.followUp], ["Not contacted in 30+ days", s.stale],
                  ["Older buyer inquiries", s.buyers], ["Older seller inquiries", s.sellers], ["Suggested reactivation candidates", s.reactivate],
                ].map(([label, n]) => (
                  <div key={label as string} className="rounded-2xl bg-white/[0.04] p-4 ring-1 ring-white/10">
                    <div className="text-2xl font-semibold tabular-nums">{(n as number).toLocaleString()}</div>
                    <div className="mt-1 text-xs leading-snug text-zinc-400">{label}</div>
                    <div className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-amber-400/80">Sample</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
              <nav className="flex gap-2 overflow-x-auto lg:flex-col">
                {CATEGORIES.map((c) => (
                  <button key={c.key} type="button" onClick={() => setCat(c.key)}
                    className={cn("flex shrink-0 items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm transition",
                      cat === c.key ? "bg-zinc-900 text-white" : "bg-white text-zinc-700 ring-1 ring-zinc-900/[0.06] hover:bg-zinc-50")}>
                    <c.icon className={cn("h-4 w-4", cat === c.key ? "text-brand-400" : "text-zinc-400")} />
                    <span className="flex-1 font-medium">{c.title}</span>
                    <span className={cn("text-xs tabular-nums", cat === c.key ? "text-zinc-400" : "text-zinc-400")}>{c.count(s)}</span>
                  </button>
                ))}
              </nav>

              <div className="min-w-0 rounded-3xl bg-white p-5 shadow-sm ring-1 ring-zinc-900/[0.06] sm:p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-lg font-semibold text-zinc-900">{category.title}</h3>
                    <p className="mt-0.5 text-sm text-zinc-500">{category.blurb}</p>
                  </div>
                  <LockedButton primary onClick={lock}><Bot className="h-3.5 w-3.5" /> Launch Radar campaign</LockedButton>
                </div>
                <div className="mt-5 grid gap-3 md:grid-cols-2">
                  {LEADS[cat].map((l) => (
                    <motion.article key={l.name} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                      className="flex flex-col rounded-2xl bg-zinc-50 p-4 ring-1 ring-zinc-900/5">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="font-semibold text-zinc-900">{l.name}</div>
                          <div className="text-[11px] font-medium uppercase tracking-wider text-brand-700">{category.title}</div>
                        </div>
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">Sample lead</span>
                      </div>
                      <dl className="mt-3 space-y-2 text-[13px]">
                        <div><dt className="text-xs text-zinc-500">Example last activity</dt><dd className="text-zinc-800">{l.activity}</dd></div>
                        <div><dt className="text-xs text-zinc-500">Potential opportunity</dt><dd className="text-zinc-800">{l.opportunity}</dd></div>
                        <div><dt className="text-xs text-zinc-500">Recommended next step</dt><dd className="text-zinc-800">{l.next}</dd></div>
                        <div><dt className="text-xs text-zinc-500">Example AI outreach</dt><dd className="italic text-zinc-700">{l.ai}</dd></div>
                      </dl>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <LockedButton onClick={lock}><Bot className="h-3.5 w-3.5" /> Call with AI</LockedButton>
                        <LockedButton onClick={lock}>Add to campaign</LockedButton>
                      </div>
                    </motion.article>
                  ))}
                </div>
                <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4">
                  <p className="max-w-xl text-xs text-zinc-500">
                    Radar suggests follow-up opportunities from activity in your CRM — they&apos;re prompts to review, not predictions of intent or results. Always check consent and do-not-call status before calling.
                  </p>
                  <LockedButton onClick={lock}>View all {category.count(s)} leads</LockedButton>
                </div>
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>
      <UnlockModal open={locked} onClose={() => setLocked(false)} />
    </div>
  );
}
