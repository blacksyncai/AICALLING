import { CalendarCheck, Mic, PhoneCall, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/Logo";

const POINTS = [
  { icon: Mic, title: "Human-sounding voice agents", text: "Built from your script, your offer and your voice." },
  { icon: PhoneCall, title: "Calls that run themselves", text: "Campaigns dial your list, follow up and log every call." },
  { icon: CalendarCheck, title: "Meetings on your calendar", text: "Qualified prospects book straight into your schedule." },
];

/** Split sign-in frame: brand story on the left (large screens), the form on the right. */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <section className="relative hidden overflow-hidden bg-zinc-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(700px_420px_at_10%_0%,rgba(236,101,60,0.28),transparent_65%),radial-gradient(600px_400px_at_100%_100%,rgba(245,158,11,0.12),transparent_70%)]" />
        <div className="pointer-events-none absolute inset-0 opacity-[0.06] [background-image:linear-gradient(rgba(255,255,255,0.6)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.6)_1px,transparent_1px)] [background-size:48px_48px]" />
        <div className="relative">
          <Logo className="text-white" />
        </div>
        <div className="relative max-w-md">
          <h2 className="font-display text-4xl font-semibold leading-[1.1] tracking-tight">
            Your AI sales team,
            <br />
            <span className="bg-gradient-to-r from-brand-400 via-orange-300 to-amber-300 bg-clip-text text-transparent">on every call.</span>
          </h2>
          <ul className="mt-10 space-y-6">
            {POINTS.map(({ icon: Icon, title: t, text }) => (
              <li key={t} className="flex gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/[0.06] ring-1 ring-inset ring-white/10">
                  <Icon className="h-5 w-5 text-brand-400" />
                </span>
                <span>
                  <span className="block text-sm font-semibold">{t}</span>
                  <span className="mt-0.5 block text-sm text-zinc-400">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative flex items-center gap-2 text-xs text-zinc-500">
          <ShieldCheck className="h-4 w-4" /> Your data stays private to your workspace.
        </p>
      </section>
      <section className="app-canvas flex flex-col items-center justify-center gap-7 px-4 py-12">
        <div className="flex w-full max-w-sm flex-col items-center gap-4 text-center">
          <span className="lg:hidden">
            <Logo />
          </span>
          <div>
            <h1 className="font-display text-2xl font-semibold tracking-tight text-zinc-900">{title}</h1>
            <p className="mt-1.5 text-sm text-zinc-500">{subtitle}</p>
          </div>
        </div>
        {children}
      </section>
    </main>
  );
}
