import { SignIn } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import { AuthShell, authFormAppearance } from "@/components/auth/AuthShell";
import { clerkEnabled } from "@/lib/clerk-server";
import { satelliteAuthRedirect } from "@/lib/branding-server";

export const dynamic = "force-dynamic";

export const metadata = { title: "Sign in" };

export default async function SignInPage() {
  if (!clerkEnabled()) redirect("/login");
  const satellite = await satelliteAuthRedirect("sign-in");
  if (satellite) redirect(satellite);
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to your BlackSync workspace.">
      <SignIn fallbackRedirectUrl="/dashboard" appearance={authFormAppearance} />
    </AuthShell>
  );
}
