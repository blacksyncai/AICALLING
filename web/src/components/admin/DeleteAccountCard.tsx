"use client";

import { AlertTriangle, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, Field, Input, Modal, Notice } from "@/components/ui";
import { api } from "@/lib/api";

/** Danger zone: permanently delete an account (type its name to confirm). */
export function DeleteAccountCard({ org }: { org: { id: string; name: string } }) {
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function remove() {
    setBusy(true);
    setError("");
    try {
      await api(`/api/admin/orgs/${org.id}`, { method: "DELETE", body: JSON.stringify({ confirm_name: typed }) });
      toast(`${org.name} was deleted`);
      router.replace("/admin");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card className="border-red-200/80 p-5">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-red-700">
        <AlertTriangle className="h-4 w-4" /> Danger zone
      </h3>
      <p className="mt-1 text-xs text-zinc-600">
        Permanently delete this account with its agents, contacts, calls, recordings list, campaigns and billing history. This can&apos;t be undone.
      </p>
      <Button variant="danger" size="sm" className="mt-3" onClick={() => { setTyped(""); setError(""); setOpen(true); }}>
        <Trash2 className="h-3.5 w-3.5" /> Delete account
      </Button>

      <Modal open={open} onClose={() => !busy && setOpen(false)} title={`Delete ${org.name}?`}>
        <div className="space-y-4 text-sm">
          <Notice tone="red">
            Everything in this account is removed for good. Team logins stay, but they lose access to it. Accounts with a live
            subscription or active phone numbers can&apos;t be deleted until those are cancelled or released.
          </Notice>
          <Field label={`Type "${org.name}" to confirm`}>
            <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={org.name} autoFocus />
          </Field>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} disabled={typed.trim() !== org.name} onClick={() => void remove()}>
              Delete permanently
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  );
}
