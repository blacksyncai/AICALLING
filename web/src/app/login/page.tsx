import { redirect } from "next/navigation";
import { PasswordLogin } from "@/components/auth/PasswordLogin";
import { clerkEnabled } from "@/lib/clerk-server";

export const dynamic = "force-dynamic";

// With Clerk configured, sign-in lives at /sign-in; until then, the built-in login.
export default function LoginPage() {
  if (clerkEnabled()) redirect("/sign-in");
  return <PasswordLogin />;
}
