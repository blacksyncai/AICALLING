import { SignIn } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import { AuthShell, authFormAppearance } from "@/components/auth/AuthShell";
import { clerkEnabled } from "@/lib/clerk-server";

export const dynamic = "force-dynamic";

export const metadata = { title: "Sign in" };

export default function SignInPage() {
  if (!clerkEnabled()) redirect("/login");
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to your BlackSync workspace.">
      <SignIn fallbackRedirectUrl="/dashboard" appearance={authFormAppearance} />
    </AuthShell>
  );
}
