import { AccountGate } from "@/components/AccountGate";
import { UpgradePrompt } from "@/components/billing/UpgradePrompt";
import { SupportWidget } from "@/components/support/SupportWidget";
import { CommandPalette } from "@/components/CommandPalette";
import { ImpersonationBanner } from "@/components/ImpersonationBanner";
import { Sidebar } from "@/components/Sidebar";
import { SessionProvider } from "@/lib/session";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <AccountGate>
        <div className="min-h-screen lg:flex">
          <Sidebar />
          <main className="app-canvas min-h-screen min-w-0 flex-1">
            <ImpersonationBanner />
            <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-8">{children}</div>
          </main>
        </div>
      </AccountGate>
      <CommandPalette />
      <UpgradePrompt />
      <SupportWidget />
    </SessionProvider>
  );
}
