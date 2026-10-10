"use client";

import { LogOut } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, Field, Input } from "@/components/ui";
import { post } from "@/lib/api";
import { signOut } from "@/lib/session";

export function PasswordSecurity() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const tooShort = next.length > 0 && next.length < 8;
  const mismatch = confirm.length > 0 && confirm !== next;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next.length < 8) return toast("New password must be at least 8 characters", "error");
    if (next !== confirm) return toast("Passwords don't match", "error");
    setBusy(true);
    try {
      await post("/api/account/password", { current_password: current, new_password: next });
      toast("Password updated — other devices were signed out");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Change password" description="Changing your password signs you out on every other device." />
        <form onSubmit={submit} className="space-y-4 p-5">
          <Field label="Current password" className="sm:max-w-sm">
            <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="New password" hint={tooShort ? <span className="text-red-600">At least 8 characters.</span> : "At least 8 characters."}>
              <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
            </Field>
            <Field label="Confirm new password" hint={mismatch ? <span className="text-red-600">Passwords don&apos;t match.</span> : undefined}>
              <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
            </Field>
          </div>
          <div className="flex justify-end">
            <Button variant="primary" loading={busy} disabled={!current || next.length < 8 || next !== confirm}>
              Update password
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <CardHeader
          title="Sign out"
          description="Sign out of BlackSync on this device."
          action={
            <Button
              loading={signingOut}
              onClick={() => {
                setSigningOut(true);
                signOut();
              }}
            >
              <LogOut className="h-4 w-4" /> Sign out
            </Button>
          }
        />
      </Card>
    </div>
  );
}
