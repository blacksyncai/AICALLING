"use client";

import {
  ArrowLeft, Bell, Bot, BookOpen, CheckCircle2, Inbox, Loader2, Lock, MessageSquare, Plus, RotateCcw, Search, Send, Sparkles,
  Ticket as TicketIcon, Trash2, UserRound, UserPlus,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { AdminGuard } from "@/components/admin/shared";
import { StatusPill } from "@/components/support/SupportWidget";
import { AuthImage, Bubble, TypingDots } from "@/components/support/Thread";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, Input, PageHeader, Select, Spinner, Textarea } from "@/components/ui";
import { PillTabs } from "@/components/ui/pricing";
import { api, del, fetcher, patch, post } from "@/lib/api";
import {
  type Article, KB_CATEGORY, type SupportConversation, type SupportTicket, TICKET_CATEGORIES, TICKET_STATUS, type TicketReply,
  categoryLabel, newClientId, timeShort, useLiveConversation,
} from "@/lib/support";
import { cn } from "@/lib/utils";

type Tab = "inbox" | "tickets" | "help";

interface Summary {
  counts: Record<string, number>;
  unread_notifications: number;
  ai_available: boolean;
  ai_model: string;
}
interface Staff { id: string; name: string; email: string }
interface StaffInfo { staff: Staff[]; me: string; me_name: string; personas: string[] }

const SEND_AS_KEY = "bs-support-send-as";

/** The team name this staff member replies as ("" = their own name), remembered on this browser. */
function useSendAs(): [string, (v: string) => void] {
  const [v, setV] = useState("");
  useEffect(() => {
    try { setV(localStorage.getItem(SEND_AS_KEY) ?? ""); } catch {}
    const on = (e: Event) => setV((e as CustomEvent<string>).detail);
    window.addEventListener("support-send-as", on);
    return () => window.removeEventListener("support-send-as", on);
  }, []);
  const set = (next: string) => {
    try { localStorage.setItem(SEND_AS_KEY, next); } catch {}
    window.dispatchEvent(new CustomEvent("support-send-as", { detail: next }));
  };
  return [v, set];
}

function SendAsPicker() {
  const toast = useToast();
  const { data, mutate } = useSWR<StaffInfo>("/api/admin/support/staff", fetcher);
  const [sendAs, setSendAs] = useSendAs();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const personas = data?.personas ?? [];
  useEffect(() => { if (data && sendAs && !personas.includes(sendAs)) setSendAs(""); }, [data, sendAs, personas, setSendAs]);
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-zinc-600">
      Send as
      <select value={sendAs} onChange={(e) => {
        if (e.target.value === "__edit") { setDraft(personas.join("\n")); setEditing(true); return; }
        setSendAs(e.target.value);
      }} aria-label="Send as" className="h-7 rounded-lg border border-zinc-200 bg-white px-2 text-xs font-medium text-zinc-900">
        <option value="">{data?.me_name ?? "Myself"} (me)</option>
        {personas.map((p) => <option key={p} value={p}>{p}</option>)}
        <option value="__edit">Edit names…</option>
      </select>
      {editing && (
        <span data-solid className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/40 p-4" onMouseDown={() => setEditing(false)}>
          <span className="block w-full max-w-sm rounded-2xl bg-white p-5 text-zinc-900 shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
            <span className="block text-sm font-semibold">Team names</span>
            <span className="mt-1 block text-xs text-zinc-500">One per line. Customers see the name you pick on your messages.</span>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={6} className="mt-3 w-full rounded-xl border border-zinc-200 p-2 text-sm" />
            <span className="mt-3 flex justify-end gap-2">
              <Button size="sm" onClick={() => setEditing(false)}>Cancel</Button>
              <Button size="sm" variant="primary" onClick={async () => {
                try {
                  await api("/api/admin/support/personas", { method: "PUT", body: JSON.stringify({ personas: draft.split("\n") }) });
                  await mutate();
                  setEditing(false);
                  toast("Team names saved");
                } catch (e) { toast((e as Error).message, "error"); }
              }}>Save</Button>
            </span>
          </span>
        </span>
      )}
    </span>
  );
}

export default function SupportAdminPage() {
  return (
    <AdminGuard>
      <SupportAdmin />
    </AdminGuard>
  );
}

/** Wakes on any support change (server long poll) and bumps a counter the lists refetch on. */
function useStaffPulse() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();
    (async () => {
      let since = 0;
      while (alive) {
        try {
          const r = await api<{ at: number }>(`/api/admin/support/poll?since=${since}&wait=25`, { signal: ctrl.signal });
          since = r.at;
          if (alive) setTick((t) => t + 1);
        } catch {
          if (!alive) return;
          await new Promise((res) => setTimeout(res, 4000));
        }
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, []);
  return tick;
}

function SupportAdmin() {
  const [tab, setTab] = useState<Tab>("inbox");
  const [openConv, setOpenConv] = useState<string | null>(null);
  const [openTicket, setOpenTicket] = useState<string | null>(null);
  const tick = useStaffPulse();
  const { data: summary, mutate: mutateSummary } = useSWR<Summary>("/api/admin/support/summary", fetcher, { refreshInterval: 60000 });
  const { data: staff } = useSWR<StaffInfo>("/api/admin/support/staff", fetcher);
  useEffect(() => { void mutateSummary(); }, [tick, mutateSummary]);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("c")) setOpenConv(p.get("c"));
    if (p.get("t")) { setTab("tickets"); setOpenTicket(p.get("t")); }
  }, []);
  useEffect(() => {
    const n = (summary?.counts.waiting ?? 0);
    document.title = n ? `(${n}) Support · BlackSync` : "Support · BlackSync";
  }, [summary?.counts.waiting]);

  return (
    <>
      <Link href="/admin" className="mb-3 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900">
        <ArrowLeft className="h-4 w-4" /> Admin portal
      </Link>
      <PageHeader
        title="Support"
        description={summary ? `AI: ${summary.ai_available ? summary.ai_model : "off"} · ${summary.counts.waiting} waiting for a person · ${summary.counts.open_tickets} open tickets` : "Customer chats, tickets and the help center."}
        action={<Notifications tick={tick} unread={summary?.unread_notifications ?? 0} onOpen={(n) => {
          if (n.conversation_id) { setTab("inbox"); setOpenConv(n.conversation_id); }
          else if (n.ticket_id) { setTab("tickets"); setOpenTicket(n.ticket_id); }
          void mutateSummary();
        }} />}
      />
      <div className="mb-5">
        <PillTabs value={tab} onChange={setTab} layoutId="support-tab" tabs={[
          { value: "inbox", label: `Inbox${summary?.counts.waiting ? ` · ${summary.counts.waiting}` : ""}`, icon: <Inbox className="h-4 w-4" /> },
          { value: "tickets", label: "Tickets", icon: <TicketIcon className="h-4 w-4" /> },
          { value: "help", label: "Help Center", icon: <BookOpen className="h-4 w-4" /> },
        ]} />
      </div>
      {tab === "inbox" && <InboxTab tick={tick} openId={openConv} setOpenId={setOpenConv} staff={staff?.staff ?? []} me={staff?.me}
        counts={summary?.counts} openTicket={(id) => { setTab("tickets"); setOpenTicket(id); }} />}
      {tab === "tickets" && <TicketsTab tick={tick} openId={openTicket} setOpenId={setOpenTicket} staff={staff?.staff ?? []}
        openConv={(id) => { setTab("inbox"); setOpenConv(id); }} />}
      {tab === "help" && <HelpTab />}
    </>
  );
}

// ── Notifications ─────────────────────────────────────────────────────────────

interface Note { id: string; kind: string; text: string; read: boolean; conversation_id: string | null; ticket_id: string | null; created_at: string | null }

function Notifications({ tick, unread, onOpen }: { tick: number; unread: number; onOpen: (n: Note) => void }) {
  const [open, setOpen] = useState(false);
  const { data, mutate } = useSWR<{ notifications: Note[] }>(open ? "/api/admin/support/notifications" : null, fetcher);
  useEffect(() => { if (open) void mutate(); }, [tick, open, mutate]);
  return (
    <div className="relative">
      <Button onClick={() => { setOpen((o) => !o); if (!open && unread) void post("/api/admin/support/notifications/read"); }}>
        <Bell className="h-4 w-4" /> Notifications
        {unread > 0 && <span className="rounded-full bg-brand-500 px-1.5 text-[11px] font-semibold text-white">{unread}</span>}
      </Button>
      {open && (
        <div data-solid className="absolute right-0 z-30 mt-2 w-80 overflow-hidden rounded-2xl bg-white shadow-xl ring-1 ring-zinc-900/10">
          {!data ? <div className="flex justify-center p-6"><Spinner /></div> : data.notifications.length === 0 ? (
            <p className="p-6 text-center text-sm text-zinc-500">Nothing yet.</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {data.notifications.map((n) => (
                <li key={n.id}>
                  <button type="button" onClick={() => { setOpen(false); onOpen(n); }}
                    className={cn("block w-full border-b border-zinc-100 px-4 py-3 text-left text-sm hover:bg-zinc-50", !n.read && "bg-brand-50/50")}>
                    <span className="block text-zinc-800">{n.text}</span>
                    <span className="text-[11px] text-zinc-400">{timeShort(n.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ── Inbox ─────────────────────────────────────────────────────────────────────

const FILTERS: [string, string][] = [
  ["all", "All"], ["waiting", "Waiting for Human"], ["human", "Human Active"], ["ai", "AI Active"], ["open_tickets", "Open Tickets"], ["resolved", "Resolved"],
];

function InboxTab({ tick, openId, setOpenId, staff, me, counts, openTicket }: {
  tick: number; openId: string | null; setOpenId: (id: string | null) => void; staff: Staff[]; me?: string;
  counts?: Record<string, number>; openTicket: (id: string) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const t = setTimeout(() => setQ(query.trim()), 300); return () => clearTimeout(t); }, [query]);
  const { data, mutate } = useSWR<{ conversations: SupportConversation[]; total: number }>(
    `/api/admin/support/conversations?filter=${filter}&q=${encodeURIComponent(q)}`, fetcher, { keepPreviousData: true });
  useEffect(() => { void mutate(); }, [tick, mutate]);

  return (
    <div className="grid min-h-[70vh] gap-4 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
      <Card className={cn("flex min-w-0 flex-col p-0", openId && "max-lg:hidden")}>
        <div className="space-y-2 border-b border-zinc-100 p-3">
          <label className="flex items-center gap-2 rounded-xl bg-zinc-100 px-3 py-2">
            <Search className="h-4 w-4 text-zinc-400" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Customer, account, #ticket or text" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
          </label>
          <div className="flex flex-wrap gap-1">
            {FILTERS.map(([k, l]) => (
              <button key={k} type="button" onClick={() => setFilter(k)}
                className={cn("rounded-full px-2.5 py-1 text-[11px] font-medium", filter === k ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200")}>
                {l}{counts && counts[k] ? ` ${counts[k]}` : ""}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {!data ? <div className="flex justify-center p-8"><Spinner /></div> : data.conversations.length === 0 ? (
            <p className="p-8 text-center text-sm text-zinc-500">No conversations here.</p>
          ) : data.conversations.map((c) => (
            <button key={c.id} type="button" onClick={() => setOpenId(c.id)}
              className={cn("flex w-full gap-3 border-b border-zinc-100 px-4 py-3 text-left hover:bg-zinc-50", openId === c.id && "bg-brand-50/60")}>
              <ModeDot mode={c.mode} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className={cn("truncate text-sm", c.unread ? "font-semibold text-zinc-900" : "font-medium text-zinc-800")}>{c.customer?.name || c.customer?.email || "Customer"}</span>
                  <span className="shrink-0 text-[11px] text-zinc-400">{timeShort(c.last_message_at)}</span>
                </div>
                <div className="truncate text-[11px] text-zinc-500">{c.org_name}</div>
                <div className={cn("truncate text-xs", c.unread ? "text-zinc-900" : "text-zinc-500")}>{c.last_preview || "—"}</div>
                <div className="mt-1 flex items-center gap-1.5">
                  <ModeBadge mode={c.mode} />
                  {c.assigned_to ? <span className="text-[10px] text-zinc-500">· {staff.find((s) => s.id === c.assigned_to)?.name ?? "Assigned"}</span> : <span className="text-[10px] text-zinc-400">· Unassigned</span>}
                  {c.unread && <span className="ml-auto h-2 w-2 rounded-full bg-brand-500" />}
                </div>
              </div>
            </button>
          ))}
        </div>
      </Card>
      {openId ? (
        <ConversationPanel key={openId} id={openId} staff={staff} me={me} onBack={() => setOpenId(null)} onChanged={() => void mutate()} openTicket={openTicket} />
      ) : (
        <Card className="flex items-center justify-center p-10 text-sm text-zinc-500 max-lg:hidden">
          <span className="flex items-center gap-2"><MessageSquare className="h-4 w-4" /> Pick a conversation</span>
        </Card>
      )}
    </div>
  );
}

function ModeDot({ mode }: { mode: string }) {
  const c = mode === "waiting_for_human" ? "bg-amber-500 animate-pulse" : mode === "human_active" ? "bg-emerald-500" : mode === "resolved" ? "bg-zinc-300" : "bg-brand-400";
  return <span className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", c)} />;
}

function ModeBadge({ mode }: { mode: string }) {
  const map: Record<string, [string, "amber" | "green" | "gray" | "blue"]> = {
    waiting_for_human: ["Waiting", "amber"], human_active: ["Human", "green"], ai_active: ["AI", "blue"], resolved: ["Resolved", "gray"],
  };
  const [label, tone] = map[mode] ?? [mode, "gray"];
  return <Badge tone={tone} className="text-[10px]">{label}</Badge>;
}

interface Detail {
  org: { id: string; name: string; status: string; credits: number; plan: string | null } | null;
  ticket: SupportTicket | null;
}

function ConversationPanel({ id, staff, me, onBack, onChanged, openTicket }: {
  id: string; staff: Staff[]; me?: string; onBack: () => void; onChanged: () => void; openTicket: (id: string) => void;
}) {
  const toast = useToast();
  const base = `/api/admin/support/conversations/${id}`;
  const { conversation: conv, setConversation, messages, add } = useLiveConversation(base);
  const { data: detail, mutate: mutateDetail } = useSWR<Detail>(base, fetcher);
  const [text, setText] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const lastTyping = useRef(0);
  const [sendAs] = useSendAs();
  const asName = sendAs || null;
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [messages.length, conv?.typing]);

  const act = useCallback(async (name: string, path: string, body?: unknown) => {
    setBusy(name);
    try {
      const c = await post<SupportConversation>(`${base}/${path}`, body);
      if (c && "mode" in c) setConversation(c);
      onChanged();
      void mutateDetail();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }, [base, onChanged, mutateDetail, setConversation, toast]);

  async function send() {
    const body = text.trim();
    if (!body) return;
    setBusy("send");
    try {
      const m = await post<import("@/lib/support").SupportMessage>(`${base}/messages`, { body, internal, client_id: newClientId(), as_name: internal ? null : asName });
      add([m]);
      setText("");
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function makeTicket() {
    setBusy("ticket");
    try {
      const t = await post<SupportTicket>(`${base}/ticket`, { category: "technical", priority: "normal" });
      toast(`Ticket #${t.number} created`);
      void mutateDetail();
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  if (!conv) return <Card className="flex justify-center p-10"><Spinner /></Card>;
  const mode = conv.mode;
  return (
    <Card className="flex min-w-0 flex-col p-0">
      <div className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-4 py-3">
        <button type="button" onClick={onBack} className="rounded-full p-1 text-zinc-500 hover:bg-zinc-100 lg:hidden" aria-label="Back"><ArrowLeft className="h-4 w-4" /></button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-semibold text-zinc-900">{conv.customer?.name || conv.customer?.email || "Customer"}</span>
            <ModeBadge mode={mode} />
          </div>
          <div className="truncate text-xs text-zinc-500">
            {conv.customer?.email} · <Link href={`/admin/accounts/${conv.org_id}`} className="hover:underline">{conv.org_name}</Link>
            {detail?.org && <> · {detail.org.plan ?? "No plan"} · {detail.org.credits} credits</>}
          </div>
        </div>
        <span className="inline-block w-44">
          <Select value={conv.assigned_to ?? ""} onChange={(e) => void act("assign", "assign", { user_id: e.target.value || null })} className="h-8 text-xs" aria-label="Assign representative">
            <option value="">Unassigned</option>
            {staff.map((s) => <option key={s.id} value={s.id}>{s.name}{s.id === me ? " (you)" : ""}</option>)}
          </Select>
        </span>
      </div>
      <div className="flex flex-wrap gap-2 border-b border-zinc-100 px-4 py-2">
        {mode !== "human_active" && mode !== "resolved" && (
          <Button size="sm" variant="primary" loading={busy === "takeover"} onClick={() => void act("takeover", "takeover", { as_name: asName })}><UserRound className="h-3.5 w-3.5" /> Take Over</Button>
        )}
        {mode === "human_active" && <Button size="sm" loading={busy === "ai"} onClick={() => void act("ai", "return-to-ai")}><Bot className="h-3.5 w-3.5" /> Return to AI</Button>}
        {mode !== "resolved" ? (
          <Button size="sm" loading={busy === "resolve"} onClick={() => void act("resolve", "resolve")}><CheckCircle2 className="h-3.5 w-3.5" /> Mark Resolved</Button>
        ) : (
          <Button size="sm" loading={busy === "reopen"} onClick={() => void act("reopen", "reopen", { as_name: asName })}><RotateCcw className="h-3.5 w-3.5" /> Reopen</Button>
        )}
        {detail?.ticket ? (
          <Button size="sm" onClick={() => openTicket(detail.ticket!.id)}><TicketIcon className="h-3.5 w-3.5" /> Ticket #{detail.ticket.number}</Button>
        ) : (
          <Button size="sm" loading={busy === "ticket"} onClick={() => void makeTicket()}><Plus className="h-3.5 w-3.5" /> Create Ticket</Button>
        )}
        {conv.assigned_to !== me && me && <Button size="sm" onClick={() => void act("assign", "assign", { user_id: me })}><UserPlus className="h-3.5 w-3.5" /> Assign to me</Button>}
      </div>
      <div ref={scroller} className="min-h-[360px] flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.map((m) => <Bubble key={m.seq} m={m} viewer="staff" />)}
        {conv.typing === "customer" && <TypingDots label="Customer is typing" />}
        {conv.typing === "ai" && <TypingDots label="BlackSync AI is replying" />}
      </div>
      <div className="border-t border-zinc-100 p-3">
        <div className="mb-2 flex gap-1 text-xs">
          <button type="button" onClick={() => setInternal(false)} className={cn("rounded-full px-3 py-1 font-medium", !internal ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}>Reply</button>
          <button type="button" onClick={() => setInternal(true)} className={cn("flex items-center gap-1 rounded-full px-3 py-1 font-medium", internal ? "bg-amber-500 text-white" : "text-zinc-600 hover:bg-zinc-100")}><Lock className="h-3 w-3" /> Internal note</button>
          {!internal && <span className="ml-2"><SendAsPicker /></span>}
          {!internal && mode !== "human_active" && <span className="ml-auto self-center text-[11px] text-zinc-500">Replying takes the chat over from the AI.</span>}
        </div>
        <div className={cn("flex items-end gap-2 rounded-2xl px-3 py-2", internal ? "bg-amber-50 ring-1 ring-amber-200" : "bg-zinc-100")}>
          <textarea value={text} rows={2} onChange={(e) => {
            setText(e.target.value);
            if (!internal && mode === "human_active" && Date.now() - lastTyping.current > 3000) {
              lastTyping.current = Date.now();
              void post(`${base}/typing`).catch(() => {});
            }
          }} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
            placeholder={internal ? "Only BlackSync staff see this" : "Message the customer…"} className="max-h-40 flex-1 resize-none bg-transparent text-sm outline-none" />
          <button type="button" disabled={busy === "send" || !text.trim()} onClick={() => void send()} aria-label="Send"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-500 text-white disabled:opacity-40">
            {busy === "send" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </Card>
  );
}

// ── Tickets ───────────────────────────────────────────────────────────────────

function TicketsTab({ tick, openId, setOpenId, staff, openConv }: {
  tick: number; openId: string | null; setOpenId: (id: string | null) => void; staff: Staff[]; openConv: (id: string) => void;
}) {
  const [status, setStatus] = useState("active");
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const t = setTimeout(() => setQ(query.trim()), 300); return () => clearTimeout(t); }, [query]);
  const { data, mutate } = useSWR<{ tickets: SupportTicket[]; total: number }>(
    `/api/admin/support/tickets?status=${status}&q=${encodeURIComponent(q)}`, fetcher, { keepPreviousData: true });
  useEffect(() => { void mutate(); }, [tick, mutate]);
  return (
    <div className="grid min-h-[70vh] gap-4 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
      <Card className={cn("flex min-w-0 flex-col p-0", openId && "max-lg:hidden")}>
        <div className="space-y-2 border-b border-zinc-100 p-3">
          <label className="flex items-center gap-2 rounded-xl bg-zinc-100 px-3 py-2">
            <Search className="h-4 w-4 text-zinc-400" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="#number, subject, account, email" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
          </label>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 text-xs">
            <option value="active">Open, in progress & waiting</option>
            <option value="">All tickets</option>
            {Object.entries(TICKET_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
        </div>
        <div className="flex-1 overflow-y-auto">
          {!data ? <div className="flex justify-center p-8"><Spinner /></div> : data.tickets.length === 0 ? (
            <p className="p-8 text-center text-sm text-zinc-500">No tickets.</p>
          ) : data.tickets.map((t) => (
            <button key={t.id} type="button" onClick={() => setOpenId(t.id)}
              className={cn("block w-full border-b border-zinc-100 px-4 py-3 text-left hover:bg-zinc-50", openId === t.id && "bg-brand-50/60")}>
              <div className="flex items-center justify-between gap-2 text-[11px] text-zinc-500">
                <span>#{t.number} · {t.org_name}</span><StatusPill status={t.status} />
              </div>
              <div className={cn("truncate text-sm", t.last_reply_by === "customer" && t.status !== "closed" ? "font-semibold text-zinc-900" : "text-zinc-800")}>{t.subject}</div>
              <div className="flex justify-between text-[11px] text-zinc-400">
                <span>{categoryLabel(t.category)} · {t.priority}{t.assigned_name ? ` · ${t.assigned_name}` : ""}</span><span>{timeShort(t.updated_at)}</span>
              </div>
            </button>
          ))}
        </div>
      </Card>
      {openId ? <TicketPanel key={openId} id={openId} staff={staff} onBack={() => setOpenId(null)} onChanged={() => void mutate()} openConv={openConv} />
        : <Card className="flex items-center justify-center p-10 text-sm text-zinc-500 max-lg:hidden">Pick a ticket</Card>}
    </div>
  );
}

function TicketPanel({ id, staff, onBack, onChanged, openConv }: { id: string; staff: Staff[]; onBack: () => void; onChanged: () => void; openConv: (id: string) => void }) {
  const toast = useToast();
  const url = `/api/admin/support/tickets/${id}`;
  const { data, mutate } = useSWR<{ ticket: SupportTicket; replies: TicketReply[] }>(url, fetcher, { refreshInterval: 20000 });
  const [text, setText] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sendAs] = useSendAs();
  if (!data) return <Card className="flex justify-center p-10"><Spinner /></Card>;
  const t = data.ticket;

  async function update(body: Record<string, unknown>) {
    try {
      await mutate(await patch(url, body), { revalidate: false });
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }
  async function reply(status?: string) {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await mutate(await post(`${url}/replies`, { body: text, internal, status, as_name: internal ? null : sendAs || null }), { revalidate: false });
      setText("");
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex min-w-0 flex-col p-0">
      <div className="border-b border-zinc-100 px-4 py-3">
        <div className="flex items-center gap-2">
          <button type="button" onClick={onBack} className="rounded-full p-1 text-zinc-500 hover:bg-zinc-100 lg:hidden" aria-label="Back"><ArrowLeft className="h-4 w-4" /></button>
          <span className="text-xs text-zinc-500">#{t.number}</span>
          <StatusPill status={t.status} />
          {t.conversation_id && <button type="button" onClick={() => openConv(t.conversation_id!)} className="ml-auto text-xs font-medium text-brand-700 hover:underline">Open chat</button>}
        </div>
        <h3 className="mt-1 text-base font-semibold text-zinc-900">{t.subject}</h3>
        <div className="text-xs text-zinc-500">{t.customer_name} · {t.customer_email} · <Link href={`/admin/accounts/${t.org_id}`} className="hover:underline">{t.org_name}</Link></div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Select value={t.status} onChange={(e) => void update({ status: e.target.value })} className="h-8 text-xs" aria-label="Status">
            {Object.entries(TICKET_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
          <Select value={t.priority} onChange={(e) => void update({ priority: e.target.value })} className="h-8 text-xs" aria-label="Priority">
            {["low", "normal", "high", "urgent"].map((p) => <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>)}
          </Select>
          <Select value={t.category} onChange={(e) => void update({ category: e.target.value })} className="h-8 text-xs" aria-label="Category">
            {TICKET_CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
          <Select value={t.assigned_to ?? ""} onChange={(e) => void update(e.target.value ? { assigned_to: e.target.value } : { unassign: true })} className="h-8 text-xs" aria-label="Assignee">
            <option value="">Unassigned</option>
            {staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </div>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        <div className="whitespace-pre-wrap rounded-2xl bg-zinc-50 p-3 text-[13px] text-zinc-800">{t.description}</div>
        {!!t.attachments?.length && <div className="flex flex-wrap gap-2">{t.attachments.map((a) => <AuthImage key={a.id} att={a} staff />)}</div>}
        {data.replies.map((r) => r.author_kind === "system" ? (
          <p key={r.id} className="text-center text-[11px] text-zinc-400">{r.body} · {timeShort(r.created_at)}</p>
        ) : (
          <div key={r.id} className={cn("rounded-2xl p-3 text-[13px]", r.internal ? "bg-amber-50 ring-1 ring-amber-200" : r.author_kind === "staff" ? "bg-brand-50" : "bg-zinc-100")}>
            <div className="mb-1 flex justify-between text-[11px] text-zinc-500">
              <span className="flex items-center gap-1 font-medium">{r.internal && <Lock className="h-3 w-3" />}{r.internal ? "Internal note · " : ""}{r.author_name ?? (r.author_kind === "staff" ? "BlackSync" : "Customer")}</span>
              <span>{timeShort(r.created_at)}</span>
            </div>
            <p className="whitespace-pre-wrap text-zinc-800">{r.body}</p>
            {r.attachments.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{r.attachments.map((a) => <AuthImage key={a.id} att={a} staff />)}</div>}
          </div>
        ))}
      </div>
      <div className="border-t border-zinc-100 p-3">
        <div className="mb-2 flex gap-1 text-xs">
          <button type="button" onClick={() => setInternal(false)} className={cn("rounded-full px-3 py-1 font-medium", !internal ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}>Reply to customer</button>
          <button type="button" onClick={() => setInternal(true)} className={cn("flex items-center gap-1 rounded-full px-3 py-1 font-medium", internal ? "bg-amber-500 text-white" : "text-zinc-600 hover:bg-zinc-100")}><Lock className="h-3 w-3" /> Internal note</button>
          {!internal && <span className="ml-2"><SendAsPicker /></span>}
        </div>
        <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder={internal ? "Only BlackSync staff see this" : "Write a reply…"} />
        <div className="mt-2 flex flex-wrap justify-end gap-2">
          {!internal && <Button size="sm" disabled={busy || !text.trim()} onClick={() => void reply("waiting_for_customer")}>Send & wait for customer</Button>}
          {!internal && <Button size="sm" disabled={busy || !text.trim()} onClick={() => void reply("resolved")}>Send & resolve</Button>}
          <Button size="sm" variant="primary" loading={busy} disabled={!text.trim()} onClick={() => void reply()}>{internal ? "Add note" : "Send"}</Button>
        </div>
      </div>
    </Card>
  );
}

// ── Help center ───────────────────────────────────────────────────────────────

function HelpTab() {
  const toast = useToast();
  const { data, mutate } = useSWR<{ articles: Article[]; categories: string[] }>("/api/admin/support/articles", fetcher);
  const [edit, setEdit] = useState<Partial<Article> | null>(null);
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState("");

  async function save() {
    if (!edit) return;
    setSaving(true);
    try {
      const body = { title: edit.title, category: edit.category, summary: edit.summary ?? "", body: edit.body, published: !!edit.published };
      const a = edit.id ? await patch<Article>(`/api/admin/support/articles/${edit.id}`, body) : await post<Article>("/api/admin/support/articles", body);
      setEdit(a);
      await mutate();
      toast("Article saved");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  const list = (data?.articles ?? []).filter((a) => !filter || a.title.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
      <Card className="p-0">
        <div className="flex gap-2 border-b border-zinc-100 p-3">
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter articles" className="h-9" />
          <Button size="sm" variant="primary" onClick={() => setEdit({ title: "", category: "getting_started", summary: "", body: "", published: false })}><Plus className="h-3.5 w-3.5" /> New</Button>
        </div>
        {!data ? <div className="flex justify-center p-8"><Spinner /></div> : list.map((a) => (
          <button key={a.id} type="button" onClick={() => setEdit(a)}
            className={cn("block w-full border-b border-zinc-100 px-4 py-2.5 text-left hover:bg-zinc-50", edit?.id === a.id && "bg-brand-50/60")}>
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium text-zinc-900">{a.title}</span>
              {a.published ? <Badge tone="green">Published</Badge> : <Badge tone="gray">Draft</Badge>}
            </div>
            <div className="text-[11px] text-zinc-500">{KB_CATEGORY[a.category] ?? a.category}</div>
          </button>
        ))}
      </Card>
      {edit ? (
        <Card className="space-y-3 p-5">
          <Input value={edit.title ?? ""} onChange={(e) => setEdit({ ...edit, title: e.target.value })} placeholder="Title" className="text-base font-semibold" />
          <div className="grid gap-3 sm:grid-cols-2">
            <Select value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })}>
              {Object.entries(KB_CATEGORY).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
            <label className="flex items-center gap-2 text-sm text-zinc-700">
              <input type="checkbox" checked={!!edit.published} onChange={(e) => setEdit({ ...edit, published: e.target.checked })} />
              Published (customers and the AI can use it)
            </label>
          </div>
          <Input value={edit.summary ?? ""} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} placeholder="One-line summary" />
          <Textarea rows={16} value={edit.body ?? ""} onChange={(e) => setEdit({ ...edit, body: e.target.value })} placeholder="Write the steps exactly as they are in the app." className="font-mono text-[13px]" />
          <p className="text-xs text-zinc-500"><Sparkles className="mr-1 inline h-3 w-3 text-brand-500" />The AI assistant answers only from published articles — keep them accurate.</p>
          <div className="flex justify-between gap-2">
            {edit.id ? (
              <Button onClick={async () => {
                if (!window.confirm("Delete this article?")) return;
                await del(`/api/admin/support/articles/${edit.id}`);
                setEdit(null);
                await mutate();
              }}><Trash2 className="h-4 w-4" /> Delete</Button>
            ) : <span />}
            <Button variant="primary" loading={saving} onClick={() => void save()}>Save</Button>
          </div>
        </Card>
      ) : (
        <Card className="flex items-center justify-center p-10 text-sm text-zinc-500">Pick an article or create one</Card>
      )}
    </div>
  );
}
