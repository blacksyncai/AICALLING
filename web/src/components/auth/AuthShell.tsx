import { CalendarCheck, Mic, PhoneCall, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/Logo";
import { FullScreenSignup } from "@/components/ui/full-screen-signup";

const POINTS = [
  { icon: Mic, title: "Human-sounding voice agents", text: "Built from your script, your offer and your voice." },
  { icon: PhoneCall, title: "Calls that run themselves", text: "Campaigns dial your list, follow up and log every call." },
  { icon: CalendarCheck, title: "Meetings on your calendar", text: "Qualified prospects book straight into your schedule." },
];

/** Clerk's form, flattened to sit inside the auth card (the card supplies the title). */
export const authFormAppearance = {
  elements: {
    // `!` (important): Clerk's own styles otherwise win over utility classes.
    rootBox: "w-full!",
    cardBox: "w-full! max-w-none! shadow-none! border-0! rounded-none! bg-transparent! overflow-visible!",
    // Keep some top padding: the Google button's border and Clerk's "Last used" tag sit at the very top.
    card: "shadow-none! border-0! bg-transparent! px-1! pt-4! overflow-visible!",
    header: "hidden!",
    footer: "bg-none! bg-transparent! [&>div]:bg-transparent! [&>div]:px-0!",
  },
};

/** Split sign-in frame: brand story on the left, the form on the right. */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <FullScreenSignup
      logo={<Logo className="text-white" />}
      headline={
        <>
          Your AI sales team,
          <br />
          <span className="bg-gradient-to-r from-brand-400 via-orange-300 to-amber-300 bg-clip-text text-transparent">on every call.</span>
        </>
      }
      points={POINTS}
      footnote={
        <span className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" /> Your data stays private to your workspace.
        </span>
      }
      title={title}
      subtitle={subtitle}
    >
      {children}
    </FullScreenSignup>
  );
}
