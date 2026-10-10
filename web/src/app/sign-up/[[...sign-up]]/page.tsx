import { SignUp } from "@clerk/nextjs";
import { redirect } from "next/navigation";
import { AuthShell } from "@/components/auth/AuthShell";
import { clerkEnabled } from "@/lib/clerk-server";

export const dynamic = "force-dynamic";

export const metadata = { title: "Create your login" };

export default function SignUpPage() {
  if (!clerkEnabled()) redirect("/login");
  return (
    <AuthShell title="Create your login" subtitle="Use the email your BlackSync invite was sent to.">
      <SignUp fallbackRedirectUrl="/dashboard" />
    </AuthShell>
  );
}
