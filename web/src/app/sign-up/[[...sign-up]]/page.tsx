import { SignUp } from "@clerk/nextjs";
import { AuthShell } from "@/components/auth/AuthShell";

export const metadata = { title: "Create your login" };

export default function SignUpPage() {
  return (
    <AuthShell title="Create your login" subtitle="Use the email your BlackSync invite was sent to.">
      <SignUp fallbackRedirectUrl="/dashboard" />
    </AuthShell>
  );
}
