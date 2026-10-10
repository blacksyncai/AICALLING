"use client";

import { Phone } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Field, Modal, Notice, Select, Spinner } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { Agent } from "@/lib/types";

export function CallNowModal({
  open,
  onClose,
  contactId,
  contactName,
  phone,
  onCalled,
}: {
  open: boolean;
  onClose: () => void;
  contactId: string;
  contactName: string;
  phone: string;
  onCalled: () => void;
}) {
  const toast = useToast();
  const { data: agents } = useSWR<Agent[]>(open ? "/api/agents/" : null, fetcher);
  const [agentId, setAgentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [callId, setCallId] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId && agents?.length) setAgentId((agents.find((a) => a.status === "active") ?? agents[0]).id);
  }, [agents, agentId]);

  useEffect(() => {
    if (open) {
      setError(null);
      setCallId(null);
    }
  }, [open]);

  async function call() {
    setBusy(true);
    setError(null);
    try {
      const res = await post<{ call_id: string; status: string }>(`/api/contacts/${contactId}/call`, { agent_id: agentId });
      toast(`Calling ${contactName}…`);
      setCallId(res.call_id);
      onCalled();
    } catch (e) {
      setError((e as Error).message);
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={`Call ${contactName}`}>
      {callId ? (
        <div className="space-y-4">
          <Notice tone="green">
            Dialing <span className="font-mono">{phone}</span> now. Follow along live from the call page.
          </Notice>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Close</Button>
            <Link
              href={`/calls/${callId}`}
              className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700"
            >
              View call
            </Link>
          </div>
        </div>
      ) : !agents ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : agents.length === 0 ? (
        <div className="space-y-4">
          <Notice>
            You need an agent before you can place a call.{" "}
            <Link href="/agents" className="font-medium underline">
              Create one
            </Link>
          </Notice>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600">
            Your AI agent will dial <span className="font-mono text-zinc-900">{phone}</span> right away.
          </p>
          <Field label="Agent">
            <Select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {a.status === "paused" ? " (paused)" : ""}
                </option>
              ))}
            </Select>
          </Field>
          {error && <Notice tone="red">{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" onClick={call} loading={busy} disabled={!agentId}>
              <Phone className="h-4 w-4" /> Call now
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
