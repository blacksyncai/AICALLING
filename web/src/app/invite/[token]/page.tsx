"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { Badge, Button, Field, Input, Notice, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

interface InviteInfo {
  email: string;
  org_name: string;
  role: "owner" | "admin" | "member";
  existing_user: boolean;
}

const card = "w-full max-w-sm space-y-4 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8";

export default function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [loadError, setLoadError] = useState("");

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<InviteInfo>(`/api/auth/invites/${encodeURIComponent(token)}`)
      .then(setInvite)
      .catch((err: Error) => setLoadError(err.message || "This invite link isn't valid."));
  }, [token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!invite) return;
    setError("");
    if (!invite.existing_user) {
      if (password.length < 8) return setError("Password must be at least 8 characters.");
      if (password !== confirm) return setError("Passwords don't match.");
    }
    setBusy(true);
    try {
      const body = invite.existing_user
        ? { password }
        : { first_name: firstName.trim(), last_name: lastName.trim(), password };
      await api(`/api/auth/invites/${encodeURIComponent(token)}/accept`, { method: "POST", body: JSON.stringify(body) });
      // Full navigation so the app loads fresh with the new session cookie.
      window.location.href = "/dashboard";
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  let content: React.ReactNode;
  if (loadError) {
    content = (
      <div className={card}>
        <Logo />
        <div>
          <h1 className="text-lg font-semibold">Invite unavailable</h1>
          <p className="text-sm text-zinc-500">Ask whoever invited you to send a new link.</p>
        </div>
        <Notice tone="red">{loadError}</Notice>
        <Link href="/login" className="block text-center text-sm font-medium text-brand-700 hover:underline">
          Go to sign in
        </Link>
      </div>
    );
  } else if (!invite) {
    content = (
      <div className={`${card} flex flex-col items-center py-12`}>
        <Spinner />
      </div>
    );
  } else {
    content = (
      <form onSubmit={submit} className={card}>
        <Logo />
        <div>
          <h1 className="text-lg font-semibold">Join {invite.org_name} on BlackSync</h1>
          <p className="text-sm text-zinc-500">
            {invite.existing_user ? (
              <>You already have a BlackSync login — enter your password to join {invite.org_name}.</>
            ) : (
              <>
                You&apos;ve been invited as <Badge className="capitalize">{invite.role}</Badge>. Set up your login to get started.
              </>
            )}
          </p>
        </div>
        {error && <Notice tone="red">{error}</Notice>}
        <Field label="Email">
          <Input type="email" value={invite.email} readOnly disabled className="bg-zinc-50 text-zinc-600" />
        </Field>
        {!invite.existing_user && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name">
              <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} autoComplete="given-name" autoFocus required />
            </Field>
            <Field label="Last name">
              <Input value={lastName} onChange={(e) => setLastName(e.target.value)} autoComplete="family-name" />
            </Field>
          </div>
        )}
        <Field label="Password" hint={invite.existing_user ? undefined : "At least 8 characters."}>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={invite.existing_user ? "current-password" : "new-password"}
            autoFocus={invite.existing_user}
            required
          />
        </Field>
        {!invite.existing_user && (
          <Field label="Confirm password">
            <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
          </Field>
        )}
        <Button variant="primary" className="w-full" loading={busy}>
          {invite.existing_user ? `Join ${invite.org_name}` : "Create account & join"}
        </Button>
        <p className="text-center text-xs text-zinc-500">
          Not {invite.email}?{" "}
          <Link href="/login" className="font-medium text-zinc-700 hover:underline">
            Sign in instead
          </Link>
        </p>
      </form>
    );
  }

  return <main className="flex min-h-screen items-center justify-center p-4">{content}</main>;
}
