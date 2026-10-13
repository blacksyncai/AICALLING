"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { sessionToken } from "@/lib/clerk";

export type Mode = "ai_active" | "waiting_for_human" | "human_active" | "resolved";

export interface SupportAttachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
}

export interface SupportMessage {
  id: string;
  seq: number;
  sender: "customer" | "ai" | "agent" | "system";
  author_name: string | null;
  body: string;
  internal: boolean;
  attachments: SupportAttachment[];
  meta: { offer_escalation?: boolean; offer_ticket?: boolean; articles?: { slug: string; title: string }[]; ticket?: { id: string; number: number } };
  client_id: string | null;
  created_at: string | null;
}

export interface SupportConversation {
  id: string;
  mode: Mode;
  subject: string;
  last_seq: number;
  last_message_at: string | null;
  last_preview: string;
  ticket_id: string | null;
  created_at: string | null;
  typing: "ai" | "agent" | "customer" | null;
  agent_name: string | null;
  unread: boolean;
  // staff view
  org_id?: string;
  org_name?: string;
  assigned_to?: string | null;
  customer?: { id: string; name: string; email: string } | null;
}

export interface SupportTicket {
  id: string;
  number: number;
  subject: string;
  description: string;
  category: string;
  priority: string;
  status: string;
  conversation_id: string | null;
  assigned_name: string | null;
  last_reply_by: string | null;
  last_reply_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  customer_name: string | null;
  unread: boolean;
  attachments?: SupportAttachment[];
  org_id?: string;
  org_name?: string;
  assigned_to?: string | null;
  customer_email?: string | null;
}

export interface TicketReply {
  id: string;
  author_kind: "customer" | "staff" | "system";
  author_name: string | null;
  body: string;
  internal: boolean;
  attachments: SupportAttachment[];
  created_at: string | null;
}

export interface Article {
  id: string;
  slug: string;
  title: string;
  category: string;
  summary: string;
  published: boolean;
  updated_at: string | null;
  body?: string;
}

export const TICKET_CATEGORIES: [string, string][] = [
  ["technical", "Technical Issue"], ["agent_setup", "AI Agent Setup"], ["telephony", "Calling / Telephony"],
  ["campaigns", "Campaigns"], ["billing", "Billing & Credits"], ["integrations", "Integrations"],
  ["feature_request", "Feature Request"], ["other", "Other"],
];
export const TICKET_STATUS: Record<string, string> = {
  open: "Open", in_progress: "In Progress", waiting_for_customer: "Waiting for Customer", resolved: "Resolved", closed: "Closed",
};
export const KB_CATEGORY: Record<string, string> = {
  getting_started: "Getting Started", agent_builder: "Agent Builder", outbound_campaigns: "Outbound Campaigns",
  phone_numbers: "Phone Numbers", call_transfers: "Call Transfers", credits_billing: "Credits and Billing",
  crm_integrations: "CRM Integrations", account_settings: "Account Settings", troubleshooting: "Troubleshooting",
};

export const categoryLabel = (k: string) => TICKET_CATEGORIES.find(([v]) => v === k)?.[1] ?? k;

/** Strip the AI's "offer a person" marker (also while it's half-streamed). */
export const cleanAi = (t: string) => t.replace(/\[\[OFFER_PERSON\]\]/g, "").replace(/\[\[[A-Z_]*\]?$/, "").trimEnd();

export function newClientId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

export function mergeMessages(prev: SupportMessage[], incoming: SupportMessage[]): SupportMessage[] {
  if (!incoming.length) return prev;
  const bySeq = new Map(prev.map((m) => [m.seq, m]));
  for (const m of incoming) bySeq.set(m.seq, m);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/** POST that reads newline-delimited JSON events as they arrive (AI replies stream this way). */
export async function streamPost(path: string, body: unknown, onEvent: (e: Record<string, unknown>) => void): Promise<void> {
  const token = await sessionToken();
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") msg = j.detail;
    } catch {}
    throw new ApiError(res.status, msg);
  }
  const reader = res.body?.getReader();
  if (!reader) return;
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) {
        try {
          onEvent(JSON.parse(line));
        } catch {}
      }
    }
  }
}

export async function uploadScreenshot(file: File, staff = false): Promise<SupportAttachment> {
  const token = await sessionToken();
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(staff ? "/api/admin/support/attachments" : "/api/support/attachments", {
    method: "POST", body: fd, headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, typeof j.detail === "string" ? j.detail : "Upload failed");
  return j as SupportAttachment;
}

/**
 * Live conversation: loads the history, then long-polls for anything newer (the server holds each
 * request until a message arrives or ~25 s pass). Survives errors by backing off.
 */
export function useLiveConversation(base: string | null) {
  const [conversation, setConversation] = useState<SupportConversation | null>(null);
  const [messages, setMessages] = useState<SupportMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);

  const add = useCallback((incoming: SupportMessage[]) => {
    setMessages((prev) => {
      const next = mergeMessages(prev, incoming);
      last.current = Math.max(last.current, ...next.map((m) => m.seq));
      return next;
    });
  }, []);

  useEffect(() => {
    if (!base) return;
    let alive = true;
    const ctrl = new AbortController();
    last.current = 0;
    setMessages([]);
    setConversation(null);
    (async () => {
      try {
        const first = await api<{ conversation: SupportConversation; messages: SupportMessage[] }>(base, { signal: ctrl.signal });
        if (!alive) return;
        setConversation(first.conversation);
        add(first.messages);
      } catch (e) {
        if (alive) setError((e as Error).message);
        return;
      }
      let backoff = 1000;
      while (alive) {
        try {
          const r = await api<{ conversation: SupportConversation; messages: SupportMessage[] }>(
            `${base}/poll?after=${last.current}&wait=25`, { signal: ctrl.signal });
          if (!alive) return;
          setConversation(r.conversation);
          add(r.messages);
          backoff = 1000;
        } catch (e) {
          if (!alive || (e as Error).name === "AbortError") return;
          if (e instanceof ApiError && e.status === 404) return;
          await new Promise((res) => setTimeout(res, backoff));
          backoff = Math.min(backoff * 2, 15000);
        }
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [base, add]);

  return { conversation, setConversation, messages, add, error };
}

export function timeShort(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = new Date().toDateString() === d.toDateString();
  return sameDay ? d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
