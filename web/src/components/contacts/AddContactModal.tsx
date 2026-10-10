"use client";

import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Field, Input, Modal, Select } from "@/components/ui";
import { post } from "@/lib/api";
import type { Campaign, Contact } from "@/lib/types";
import { parseTags } from "./shared";

const EMPTY = { name: "", phone: "", email: "", company: "", role: "", tags: "", campaign_id: "" };

export function AddContactModal({
  open,
  onClose,
  campaigns,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  campaigns: Campaign[];
  onCreated: (c: Contact) => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const c = await post<Contact>("/api/contacts", {
        name: form.name.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        company: form.company.trim(),
        role: form.role.trim(),
        notes: "",
        tags: parseTags(form.tags),
        campaign_id: form.campaign_id || null,
      });
      toast(`Added ${c.name || c.phone}`);
      setForm(EMPTY);
      onCreated(c);
      onClose();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Add contact">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <Input value={form.name} onChange={set("name")} placeholder="Jane Cooper" autoFocus />
        </Field>
        <Field label="Phone *">
          <Input value={form.phone} onChange={set("phone")} placeholder="+14155550123" required inputMode="tel" />
        </Field>
        <Field label="Email">
          <Input type="email" value={form.email} onChange={set("email")} placeholder="jane@acme.com" />
        </Field>
        <Field label="Company">
          <Input value={form.company} onChange={set("company")} />
        </Field>
        <Field label="Role">
          <Input value={form.role} onChange={set("role")} placeholder="Head of Sales" />
        </Field>
        <Field label="Campaign">
          <Select value={form.campaign_id} onChange={set("campaign_id")}>
            <option value="">No campaign</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Tags" hint="Comma-separated, e.g. vip, inbound" className="sm:col-span-2">
          <Input value={form.tags} onChange={set("tags")} />
        </Field>
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy}>
            Add contact
          </Button>
        </div>
      </form>
    </Modal>
  );
}
