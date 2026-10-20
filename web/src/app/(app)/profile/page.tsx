"use client";

import { CallAlertSettings } from "@/components/notifications/CallAlerts";
import { BellRing, Building2, KeyRound, UserRound, Users } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, type ReactNode } from "react";
import { OrgTab } from "@/components/profile/OrgTab";
import { ProfileTab } from "@/components/profile/ProfileTab";
import { SecurityTab } from "@/components/profile/SecurityTab";
import { TeamTab } from "@/components/profile/TeamTab";
import { PageHeader, Spinner } from "@/components/ui";
import { cn } from "@/lib/utils";

const TABS = [
  { value: "profile", label: "Profile", icon: UserRound },
  { value: "security", label: "Security", icon: KeyRound },
  { value: "team", label: "Team", icon: Users },
  { value: "alerts", label: "Call alerts", icon: BellRing },
  { value: "organization", label: "Organization", icon: Building2 },
] as const;

type Tab = (typeof TABS)[number]["value"];

const PANELS: Record<Tab, () => ReactNode> = {
  profile: () => <ProfileTab />,
  security: () => <SecurityTab />,
  team: () => <TeamTab />,
  organization: () => <OrgTab />,
  alerts: () => <CallAlertSettings />,
};

function ProfileContent() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get("tab");
  // Credits moved to Billing & Usage.
  useEffect(() => {
    if (raw === "billing") router.replace("/billing?tab=credits");
  }, [raw, router]);
  const tab: Tab = TABS.some((t) => t.value === raw) ? (raw as Tab) : "profile";

  function select(next: Tab) {
    const p = new URLSearchParams(params.toString());
    if (next === "profile") p.delete("tab");
    else p.set("tab", next);
    const qs = p.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  return (
    <>
      <PageHeader title="Account" description="Your profile, sign-in and team." />
      <div className="-mx-4 mb-6 overflow-x-auto border-b border-zinc-200 px-4 sm:mx-0 sm:px-0">
        <nav className="flex min-w-max gap-1" role="tablist">
          {TABS.map((t) => {
            const active = t.value === tab;
            const Icon = t.icon;
            return (
              <button
                key={t.value}
                role="tab"
                aria-selected={active}
                onClick={() => select(t.value)}
                className={cn(
                  "-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
                  active ? "border-brand-600 text-zinc-900" : "border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-800",
                )}
              >
                <Icon className={cn("h-4 w-4", active ? "text-brand-600" : "text-zinc-400")} />
                {t.label}
              </button>
            );
          })}
        </nav>
      </div>
      <div className="max-w-4xl">{PANELS[tab]()}</div>
    </>
  );
}

export default function ProfilePage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      }
    >
      <ProfileContent />
    </Suspense>
  );
}
