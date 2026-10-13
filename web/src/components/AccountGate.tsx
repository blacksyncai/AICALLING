"use client";

import { Onboarding } from "@/components/onboarding/Onboarding";
import { useSession } from "@/lib/session";

/** A login that isn't in any BlackSync account yet: start the free-trial onboarding. */
export function AccountGate({ children }: { children: React.ReactNode }) {
  const { session } = useSession();
  if (!session || session.org) return <>{children}</>;
  return <Onboarding />;
}

/** Renders its children only once the login belongs to an account (not during onboarding). */
export function WhenInAccount({ children }: { children: React.ReactNode }) {
  const { session } = useSession();
  return session?.org ? <>{children}</> : null;
}
