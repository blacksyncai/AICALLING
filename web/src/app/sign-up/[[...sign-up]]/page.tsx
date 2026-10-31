import { SignUp } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import { AuthShell, authFormAppearance } from "@/components/auth/AuthShell";
import { clerkEnabled } from "@/lib/clerk-server";
import { satelliteAuthRedirect } from "@/lib/branding-server";

export const dynamic = "force-dynamic";

export const metadata = { title: "Create your account" };

export default async function SignUpPage({ searchParams }: { searchParams: Promise<{ email?: string | string[] }> }) {
  if (!clerkEnabled()) redirect("/login");
  const satellite = await satelliteAuthRedirect("sign-up");
  if (satellite) redirect(satellite);
  // An emailed invite links here with ?email=… so the address is filled in.
  const raw = (await searchParams).email;
  const email = typeof raw === "string" && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw) ? raw.slice(0, 320) : undefined;
  return (
    <AuthShell
      title="Create your account"
      subtitle="Get started with BlackSync in seconds — no card needed. Invited by a teammate? Use the email your invite was sent to."
    >
      <SignUp fallbackRedirectUrl="/dashboard" appearance={authFormAppearance} initialValues={email ? { emailAddress: email } : undefined} />
    </AuthShell>
  );
}
