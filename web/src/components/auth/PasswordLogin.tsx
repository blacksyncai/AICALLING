"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthShell } from "@/components/auth/AuthShell";
import { Button, Field, Input, Notice } from "@/components/ui";

function LoginForm() {
  const next = useSearchParams().get("next") || "/dashboard";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setLoading(false);
    // Full navigation so the app loads fresh with the new session.
    if (res.ok) window.location.href = next;
    else setError((await res.json().catch(() => ({}))).detail ?? "Sign in failed");
  }

  return (
    <form onSubmit={submit} className="w-full space-y-4">
      {error && <Notice tone="red">{error}</Notice>}
      <Field label="Email">
        <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
      </Field>
      <Field label="Password">
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </Field>
      <Button variant="primary" className="w-full" loading={loading}>
        Sign in
      </Button>
    </form>
  );
}

/** Built-in email/password sign-in, used until Clerk is configured (CLERK_SECRET_KEY). */
export function PasswordLogin() {
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to your BlackSync workspace.">
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
