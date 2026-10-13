import { SignUp } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import { AuthShell, authFormAppearance } from "@/components/auth/AuthShell";
import { clerkEnabled } from "@/lib/clerk-server";

export const dynamic = "force-dynamic";

export const metadata = { title: "Create your account" };

export default function SignUpPage() {
  if (!clerkEnabled()) redirect("/login");
  return (
    <AuthShell
      title="Create your account"
      subtitle="Get started with BlackSync in seconds — no card needed. Invited by a teammate? Use the email your invite was sent to."
    >
      <SignUp fallbackRedirectUrl="/dashboard" appearance={authFormAppearance} />
    </AuthShell>
  );
}
