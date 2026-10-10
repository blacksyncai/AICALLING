"use client";

import { KeyRound, Plus, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice } from "@/components/ui";
import { del, post } from "@/lib/api";
import type { ApiKey } from "@/lib/types";
import { formatDateTime, timeAgo } from "@/lib/utils";
import { ConfirmModal, CopyButton } from "./shared";

export function ApiKeysCard({ keys, onChange }: { keys: ApiKey[]; onChange: () => void }) {
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  return (
    <Card>
      <CardHeader
        title="API keys"
        description="Use a key to call the BlackSync API from Zapier, Make, n8n or your own code. Treat keys like passwords."
        action={
          keys.length > 0 && (
            <Button variant="primary" size="sm" onClick={() => setCreating(true)} className="shrink-0">
              <Plus className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Create API key</span>
              <span className="sm:hidden">Create</span>
            </Button>
          )
        }
      />
      {keys.length === 0 ? (
        <EmptyState
          icon={<KeyRound className="h-5 w-5" />}
          title="No API keys"
          description="Create a key to add contacts, start calls and read results programmatically."
          action={
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" />
              Create API key
            </Button>
          }
        />
      ) : (
        <>
          <div className="hidden grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_auto] gap-4 border-b border-zinc-100 bg-zinc-50/60 px-5 py-2 text-[11px] font-medium uppercase tracking-wide text-zinc-400 md:grid">
            <span>Name</span>
            <span>Key</span>
            <span>Created</span>
            <span>Last used</span>
            <span className="w-16" />
          </div>
          <ul className="divide-y divide-zinc-100">
            {keys.map((k) => (
              <li
                key={k.id}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-5 py-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_auto]"
              >
                <span className="truncate text-sm font-medium text-zinc-900">{k.name}</span>
                <code className="order-3 truncate font-mono text-xs text-zinc-500 md:order-none">{k.prefix}…</code>
                <span className="order-4 col-span-2 text-xs text-zinc-500 md:order-none md:col-span-1" title={formatDateTime(k.created_at)}>
                  <span className="md:hidden">Created </span>
                  {timeAgo(k.created_at)}
                  <span className="md:hidden"> · Last used {k.last_used_at ? timeAgo(k.last_used_at) : "never"}</span>
                </span>
                <span className="hidden text-xs text-zinc-500 md:block" title={k.last_used_at ? formatDateTime(k.last_used_at) : undefined}>
                  {k.last_used_at ? timeAgo(k.last_used_at) : "Never"}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setRevoking(k)}
                  className="order-2 w-16 text-red-600 hover:bg-red-50 hover:text-red-700 md:order-none"
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}

      {creating && (
        <CreateKeyModal
          onClose={() => setCreating(false)}
          onCreated={onChange}
        />
      )}
      <ConfirmModal
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title="Revoke API key"
        confirmLabel="Revoke key"
        body={
          <>
            Anything using <span className="font-medium text-zinc-900">{revoking?.name}</span> (
            <code className="font-mono text-xs">{revoking?.prefix}…</code>) will stop working immediately. This can&apos;t be undone.
          </>
        }
        onConfirm={async () => {
          if (!revoking) return;
          try {
            await del(`/api/integrations/api-keys/${revoking.id}`);
            toast("API key revoked");
            setRevoking(null);
            onChange();
          } catch (e) {
            toast((e as Error).message, "error");
          }
        }}
      />
    </Card>
  );
}

function CreateKeyModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const res = await post<ApiKey & { key: string }>("/api/integrations/api-keys", { name: name.trim() || "API key" });
      setSecret(res.key);
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={secret ? "Your new API key" : "Create API key"}>
      {secret ? (
        <div className="space-y-4">
          <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-900">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <span>
              <strong className="font-semibold">You won&apos;t see this again.</strong> Copy it now and store it somewhere safe, like a password manager or
              your Zap&apos;s settings.
            </span>
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-zinc-950 p-2 pl-3">
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-zinc-100">{secret}</code>
            <CopyButton text={secret} dark />
          </div>
          <div className="flex justify-end">
            <Button variant="primary" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Name" hint="Something that tells you where it's used, e.g. “Zapier” or “HubSpot sync”.">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Zapier" autoFocus maxLength={80} />
          </Field>
          {error && <Notice tone="red">{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={saving}>
              Create key
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
