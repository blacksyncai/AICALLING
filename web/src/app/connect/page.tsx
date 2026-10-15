"use client";

import { Check, ShieldCheck } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Logo } from "@/components/Logo";
import { Button, Notice, Spinner } from "@/components/ui";
import { api, post } from "@/lib/api";

interface RequestInfo {
  client_name: string;
  redirect_host: string;
  verified: boolean;
  email: string;
  accounts: { id: string; name: string; role: string }[];
  default_account: string | null;
}

const card = "w-full max-w-md space-y-5 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8";

const CAN = [
  "See your agents, calls, transcripts, contacts, campaigns and results",
  "Build and edit agents and your business knowledge",
  "Add contacts and set up campaigns",
  "Place calls and start campaigns — it asks you first",
];

/** OAuth approval: an AI assistant (ChatGPT, Claude, …) asks to work in the user's BlackSync account. */
function Approve() {
  const req = useSearchParams().get("req") ?? "";
  const [info, setInfo] = useState<RequestInfo | null>(null);
  const [error, setError] = useState("");
  const [account, setAccount] = useState<string>("");
  const [busy, setBusy] = useState<"" | "allow" | "deny">("");

  useEffect(() => {
    if (!req) {
      setError("This link is missing its connection request. Start again from ChatGPT or Claude.");
      return;
    }
    api<RequestInfo>(`/api/oauth/request?req=${encodeURIComponent(req)}`)
      .then((r) => {
        setInfo(r);
        setAccount(r.default_account ?? "");
      })
      .catch((e: Error) => setError(e.message));
  }, [req]);

  async function decide(approve: boolean) {
    setBusy(approve ? "allow" : "deny");
    try {
      const r = await post<{ redirect: string }>("/api/oauth/approve", { req, approve, org_id: account || null });
      window.location.href = r.redirect;
    } catch (e) {
      setError((e as Error).message);
      setBusy("");
    }
  }

  if (error)
    return (
      <div className={card}>
        <Logo />
        <h1 className="text-lg font-semibold">Couldn&apos;t connect</h1>
        <Notice tone="red">{error}</Notice>
      </div>
    );
  if (!info) return <Spinner />;

  return (
    <div className={card}>
      <Logo />
      <div>
        <h1 className="text-lg font-semibold text-zinc-900">Connect {info.client_name} to BlackSync</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Signed in as <span className="font-medium text-zinc-800">{info.email}</span>
        </p>
      </div>

      {!info.verified && (
        <Notice tone="amber">
          This app sends you back to <strong>{info.redirect_host}</strong>, which isn&apos;t ChatGPT or Claude. Only allow it if
          you started this connection yourself from an app you trust.
        </Notice>
      )}

      {info.accounts.length > 1 && (
        <label className="block space-y-1.5 text-sm">
          <span className="font-medium text-zinc-800">Account</span>
          <select
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm"
          >
            {info.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {info.accounts.length === 1 && (
        <p className="text-sm text-zinc-600">
          Account: <span className="font-medium text-zinc-900">{info.accounts[0].name}</span>
        </p>
      )}
      {info.accounts.length === 0 && (
        <p className="text-sm text-zinc-600">
          You don&apos;t have an account yet — {info.client_name} can set one up for you once connected.
        </p>
      )}

      <div className="rounded-xl bg-zinc-50 p-4">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">{info.client_name} will be able to</div>
        <ul className="space-y-1.5 text-sm text-zinc-700">
          {CAN.map((c) => (
            <li key={c} className="flex gap-2">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> {c}
            </li>
          ))}
        </ul>
      </div>

      <p className="flex gap-2 text-xs leading-relaxed text-zinc-500">
        <ShieldCheck className="h-4 w-4 shrink-0 text-zinc-400" />
        It acts as you, with your permissions. You can disconnect it any time under Integrations. You&apos;ll return to{" "}
        {info.redirect_host}.
      </p>

      <div className="flex gap-2">
        <Button className="flex-1" disabled={!!busy} loading={busy === "deny"} onClick={() => void decide(false)}>
          Cancel
        </Button>
        <Button variant="primary" className="flex-1" disabled={!!busy} loading={busy === "allow"} onClick={() => void decide(true)}>
          Allow
        </Button>
      </div>
    </div>
  );
}

export default function ConnectPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-50 p-4">
      <Suspense fallback={<Spinner />}>
        <Approve />
      </Suspense>
    </main>
  );
}
