import { SignUp } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import { AuthShell, authFormAppearance } from "@/components/auth/AuthShell";
import { clerkEnabled } from "@/lib/clerk-server";

export const dynamic = "force-dynamic";

export const metadata = { title: "Start your free trial" };

export default function SignUpPage() {
  if (!clerkEnabled()) redirect("/login");
  return (
    <AuthShell
      title="Start your free trial"
      subtitle="Create your BlackSync account in seconds — no card needed. Invited by a teammate? Use the email your invite was sent to."
    >
      <SignUp fallbackRedirectUrl="/dashboard" appearance={authFormAppearance} />
    </AuthShell>
  );
}
