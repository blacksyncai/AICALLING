"use client";

import { Show, SignInButton, SignUpButton, useUser } from "@clerk/nextjs";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { Badge, Button, Notice, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

interface InviteInfo {
  email: string;
  org_name: string;
  role: "owner" | "admin" | "member";
  existing_user: boolean;
}

const card = "w-full max-w-sm space-y-4 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8";

function JoinButton({ token }: { token: string }) {
  const { user } = useUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function join() {
    setBusy(true);
    setError("");
    try {
      await api(`/api/auth/invites/${encodeURIComponent(token)}/join`, { method: "POST" });
      window.location.href = "/dashboard";
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {error && <Notice tone="red">{error}</Notice>}
      <Button variant="primary" className="w-full" loading={busy} onClick={join}>
        Join as {user?.primaryEmailAddress?.emailAddress ?? "you"}
      </Button>
    </div>
  );
}

export default function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const here = `/invite/${encodeURIComponent(token)}`;

  useEffect(() => {
    api<InviteInfo>(`/api/auth/invites/${encodeURIComponent(token)}`)
      .then(setInvite)
      .catch((err: Error) => setLoadError(err.message || "This invite link isn't valid."));
  }, [token]);

  let content: React.ReactNode;
  if (loadError) {
    content = (
      <div className={card}>
        <Logo />
        <h1 className="text-lg font-semibold">Invite unavailable</h1>
        <Notice tone="red">{loadError}</Notice>
        <Link href="/sign-in" className="block text-sm font-medium text-brand-600 hover:text-brand-700">
          Go to sign in →
        </Link>
      </div>
    );
  } else if (!invite) {
    content = <Spinner />;
  } else {
    content = (
      <div className={card}>
        <Logo />
        <div>
          <h1 className="text-lg font-semibold">Join {invite.org_name} on BlackSync</h1>
          <p className="mt-1 text-sm text-zinc-500">
            You&apos;ve been invited to <span className="font-medium text-zinc-800">{invite.org_name}</span> as{" "}
            <Badge tone={invite.role === "member" ? "gray" : "brand"}>{invite.role}</Badge>
          </p>
        </div>
        <Show when="signed-out">
          <p className="text-sm text-zinc-500">
            Create your login with <span className="font-medium text-zinc-800">{invite.email}</span> and you&apos;ll land
            straight in the account.
          </p>
          <SignUpButton mode="modal" forceRedirectUrl={here} initialValues={{ emailAddress: invite.email }}>
            <Button variant="primary" className="w-full">Create login & join</Button>
          </SignUpButton>
          <SignInButton mode="modal" forceRedirectUrl={here} initialValues={{ emailAddress: invite.email }}>
            <Button className="w-full">I already have a login</Button>
          </SignInButton>
        </Show>
        <Show when="signed-in">
          <JoinButton token={token} />
        </Show>
      </div>
    );
  }

  return <main className="flex min-h-screen items-center justify-center p-4">{content}</main>;
}
