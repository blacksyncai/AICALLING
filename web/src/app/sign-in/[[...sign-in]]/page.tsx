import { SignIn } from "@clerk/nextjs";
import { AuthShell } from "@/components/auth/AuthShell";

export const metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to your BlackSync workspace.">
      <SignIn fallbackRedirectUrl="/dashboard" />
    </AuthShell>
  );
}
