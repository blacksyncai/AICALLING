import { redirect } from "next/navigation";

// Sign-in moved to Clerk; keep old /login links working.
export default function LoginPage() {
  redirect("/sign-in");
}
