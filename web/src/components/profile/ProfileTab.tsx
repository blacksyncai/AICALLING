"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Field, Input, Spinner } from "@/components/ui";
import { patch } from "@/lib/api";
import { displayName, useSession } from "@/lib/session";
import type { User } from "@/lib/types";
import { Avatar, ROLE_TONE } from "./shared";

export function ProfileTab() {
  const { session, mutate } = useSession();
  const toast = useToast();
  const user = session?.user;
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "", phone: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) setForm({ first_name: user.first_name, last_name: user.last_name, email: user.email, phone: user.phone ?? "" });
  }, [user]);

  if (!session || !user) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  const dirty =
    form.first_name !== user.first_name ||
    form.last_name !== user.last_name ||
    form.email !== user.email ||
    form.phone !== (user.phone ?? "");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await patch<User>("/api/account/profile", {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
      });
      await mutate();
      toast("Profile saved");
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex min-w-0 items-center gap-4">
          <Avatar name={displayName(user)} size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-semibold text-zinc-900">{displayName(user)}</h2>
              <Badge tone={ROLE_TONE[session.role]}>{session.role}</Badge>
              {user.is_superadmin && <Badge tone="violet">Platform admin</Badge>}
            </div>
            <p className="truncate text-sm text-zinc-500">{user.email}</p>
            {session.org && <p className="truncate text-xs text-zinc-400">{session.org.name}</p>}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Personal details" description="Your name and contact details across BlackSync." />
        <form onSubmit={save} className="space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name">
              <Input value={form.first_name} onChange={set("first_name")} autoComplete="given-name" />
            </Field>
            <Field label="Last name">
              <Input value={form.last_name} onChange={set("last_name")} autoComplete="family-name" />
            </Field>
            <Field label="Email" hint="Your sign-in email — change it under Security.">
              <Input type="email" value={form.email} readOnly disabled />
            </Field>
            <Field label="Phone">
              <Input type="tel" value={form.phone} onChange={set("phone")} autoComplete="tel" placeholder="+1 555 123 4567" />
            </Field>
          </div>
          <div className="flex justify-end">
            <Button variant="primary" loading={busy} disabled={!dirty || !form.email.trim()}>
              Save changes
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
