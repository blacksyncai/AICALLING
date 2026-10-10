"use client";

import { UserProfile } from "@clerk/nextjs";
import { LogOut } from "lucide-react";
import { useState } from "react";
import { Button, Card, CardHeader } from "@/components/ui";
import { PasswordSecurity } from "@/components/profile/PasswordSecurity";
import { signOut, useSession } from "@/lib/session";

/** Sign-in email, password, connected logins, 2-step verification and devices — all handled by Clerk. */
export function SecurityTab() {
  const { session } = useSession();
  if (session?.auth_provider === "password") return <PasswordSecurity />;
  return <ClerkSecurity />;
}

function ClerkSecurity() {
  const [signingOut, setSigningOut] = useState(false);
  return (
    <div className="space-y-6">
      <div className="min-w-0 overflow-x-auto">
        <UserProfile
          routing="hash"
          appearance={{ elements: { rootBox: "w-full", cardBox: "w-full max-w-none shadow-none border border-zinc-200" } }}
        />
      </div>
      <Card>
        <CardHeader
          title="Sign out"
          description="Sign out of BlackSync on this device."
          action={
            <Button
              loading={signingOut}
              onClick={async () => {
                setSigningOut(true);
                await signOut();
              }}
            >
              <LogOut className="h-4 w-4" /> Sign out
            </Button>
          }
        />
      </Card>
    </div>
  );
}
