"use client";

import { UserButton } from "@clerk/nextjs";
import { Building2 } from "lucide-react";
import { Logo } from "@/components/Logo";
import { Button, Card } from "@/components/ui";
import { signOut, useSession } from "@/lib/session";

/** A login that isn't in any BlackSync account yet (signed up without an invite). */
export function AccountGate({ children }: { children: React.ReactNode }) {
  const { session } = useSession();
  if (!session || session.org) return <>{children}</>;
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <Logo />
      <Card className="w-full max-w-md p-8 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          <Building2 className="h-5 w-5" />
        </div>
        <h1 className="text-lg font-semibold">You&apos;re not in an account yet</h1>
        <p className="mt-2 text-sm leading-relaxed text-zinc-500">
          You&apos;re signed in as <span className="font-medium text-zinc-800">{session.user.email}</span>, but this login
          hasn&apos;t been added to a BlackSync account. Open the invite link you were sent, or ask your account owner to invite
          this email.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <UserButton />
          <Button onClick={signOut}>Use a different login</Button>
        </div>
      </Card>
    </main>
  );
}
