"use client";

import {
  ArrowLeft, BookOpen, ChevronLeft, ChevronRight, ImagePlus, Inbox, LifeBuoy, Loader2, MessageCircle, Minus, Search, Send, Sparkles,
  Ticket as TicketIcon, UserRound, X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { LogoMark } from "@/components/Logo";
import { fetcher, post } from "@/lib/api";
import {
  type Article, KB_CATEGORY, type SupportAttachment, type SupportConversation, type SupportMessage, type SupportTicket,
  TICKET_CATEGORIES, TICKET_STATUS, type TicketReply, categoryLabel, cleanAi, newClientId, streamPost, timeShort,
  uploadScreenshot, useLiveConversation,
} from "@/lib/support";
import { cn } from "@/lib/utils";
import { AuthImage, Bubble, TypingDots } from "./Thread";

type View =
  | { name: "home" }
  | { name: "chat"; id: string }
  | { name: "list"; tab?: "chats" | "tickets" }
  | { name: "new-ticket"; conversationId?: string }
  | { name: "ticket"; id: string }
  | { name: "help"; q?: string }
  | { name: "article"; slug: string };

interface State {
  unread: number;
  staff_online: boolean;
  ai_available: boolean;
  user: { name: string; email: string };
  org: string;
}

const STORE = "bs-support";
const TUCK_KEY = "bs-support-tucked";
function load(): { open: boolean; view: View } {
  try {
    const v = JSON.parse(localStorage.getItem(STORE) || "{}");
    return { open: !!v.open, view: v.view ?? { name: "home" } };
  } catch {
    return { open: false, view: { name: "home" } };
  }
}

/** BlackSync Support — the floating help button and messenger panel (bottom right of the app). */
export function SupportWidget() {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>({ name: "home" });
  const [history, setHistory] = useState<View[]>([]);
  const ready = useRef(false);
  // The × on the button tucks it into a small tab at the screen edge (remembered on this device).
  const [tucked, setTucked] = useState(false);
  useEffect(() => {
    try {
      setTucked(localStorage.getItem(TUCK_KEY) === "1");
    } catch {}
  }, []);
  const tuck = (v: boolean) => {
    setTucked(v);
    try {
      if (v) localStorage.setItem(TUCK_KEY, "1");
      else localStorage.removeItem(TUCK_KEY);
    } catch {}
  };
  const { data: st, mutate: refreshState } = useSWR<State>("/api/support/state", fetcher, { refreshInterval: open ? 20000 : 45000 });

  useEffect(() => {
    const s = load();
    setOpen(s.open);
    setView(s.view);
    ready.current = true;
  }, []);
  useEffect(() => {
    if (!ready.current) return;
    try {
      localStorage.setItem(STORE, JSON.stringify({ open, view }));
    } catch {}
  }, [open, view]);
  useEffect(() => {
    const on = () => {
      tuck(false);
      setOpen(true);
    };
    window.addEventListener("open-support", on);
    return () => window.removeEventListener("open-support", on);
  }, []);

  const go = useCallback((v: View) => {
    setHistory((h) => [...h.slice(-10), view]);
    setView(v);
  }, [view]);
  const back = () => {
    setHistory((h) => {
      const prev = h[h.length - 1];
      setView(prev ?? { name: "home" });
      return h.slice(0, -1);
    });
  };

  return (
    <>
      {open && (
        <div
          role="dialog"
          aria-label="BlackSync Support"
          className="fixed inset-0 z-[60] flex flex-col overflow-hidden bg-white shadow-2xl ring-1 ring-zinc-900/10 sm:inset-auto sm:bottom-24 sm:right-5 sm:h-[min(640px,calc(100vh-8rem))] sm:w-[390px] sm:rounded-3xl"
        >
          <Header view={view} onBack={view.name !== "home" ? back : undefined} onClose={() => setOpen(false)} st={st} />
          <div className="flex min-h-0 flex-1 flex-col">
            {view.name === "home" && <Home st={st} go={go} />}
            {view.name === "chat" && <Chat id={view.id} st={st} go={go} onSeen={() => void refreshState()} />}
            {view.name === "list" && <ListView tab={view.tab ?? "chats"} go={go} setTab={(tab) => setView({ name: "list", tab })} />}
            {view.name === "new-ticket" && <NewTicket conversationId={view.conversationId} done={(id) => { setHistory([{ name: "home" }]); setView({ name: "ticket", id }); }} />}
            {view.name === "ticket" && <TicketView id={view.id} onSeen={() => void refreshState()} />}
            {view.name === "help" && <Help initial={view.q ?? ""} go={go} />}
            {view.name === "article" && <ArticleView slug={view.slug} go={go} />}
          </div>
        </div>
      )}
      {tucked && !open ? (
        <button
          type="button"
          aria-label="Show support chat"
          onClick={() => {
            tuck(false);
            setOpen(true);
          }}
          className="fixed bottom-24 right-0 z-[61] flex h-12 w-6 items-center justify-center rounded-l-xl bg-gradient-to-br from-brand-500 to-brand-600 text-white shadow-lg shadow-brand-600/30 transition hover:w-8"
        >
          <ChevronLeft className="h-4 w-4" />
          {!!st?.unread && <span className="absolute -left-1 -top-1 h-3 w-3 rounded-full bg-zinc-950 ring-2 ring-white" />}
        </button>
      ) : (
      <div className={cn("fixed bottom-5 right-5 z-[61]", open && "max-sm:hidden")}>
      <button
        type="button"
        aria-label={open ? "Close support" : "Open support"}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-600 text-white shadow-lg shadow-brand-600/30 transition hover:scale-105 active:scale-95",
        )}
      >
        {open ? <Minus className="h-6 w-6" /> : <MessageCircle className="h-6 w-6" />}
        {!open && !!st?.unread && (
          <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-zinc-950 px-1 text-[11px] font-semibold text-white ring-2 ring-white">
            {st.unread}
          </span>
        )}
      </button>
      {!open && (
        <button
          type="button"
          aria-label="Hide support button"
          onClick={() => tuck(true)}
          className="absolute -left-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 text-white shadow ring-2 ring-white hover:bg-zinc-950"
        >
          <X className="h-3 w-3" />
        </button>
      )}
      </div>
      )}
    </>
  );
}

function Header({ view, onBack, onClose, st }: { view: View; onBack?: () => void; onClose: () => void; st?: State }) {
  const title = { home: "BlackSync Support", chat: "Support chat", list: "My conversations", "new-ticket": "New ticket",
                  ticket: "Ticket", help: "Help Center", article: "Help Center" }[view.name];
  return (
    <div className="relative shrink-0 overflow-hidden bg-zinc-950 px-4 py-3.5 text-white">
      <div className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-brand-500/30 blur-3xl" />
      <div className="relative flex items-center gap-3">
        {onBack ? (
          <button type="button" onClick={onBack} aria-label="Back" className="-ml-1 rounded-full p-1.5 text-zinc-300 hover:bg-white/10 hover:text-white">
            <ArrowLeft className="h-4 w-4" />
          </button>
        ) : (
          <LogoMark className="h-8 w-8" />
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{title}</div>
          {view.name === "home" && (
            <div className="flex items-center gap-1.5 text-[11px] text-zinc-400">
              <span className={cn("h-1.5 w-1.5 rounded-full", st?.staff_online ? "bg-emerald-400" : "bg-zinc-500")} />
              {st?.staff_online ? "The team is online" : "AI answers now · the team replies by ticket"}
            </div>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label="Minimize" className="rounded-full p-1.5 text-zinc-300 hover:bg-white/10 hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ── Home ──────────────────────────────────────────────────────────────────────

function Home({ st, go }: { st?: State; go: (v: View) => void }) {
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const { data: convs } = useSWR<{ conversations: SupportConversation[] }>("/api/support/conversations?limit=1", fetcher);
  const recent = convs?.conversations[0];
  const first = st?.user.name?.split(" ")[0];

  async function startChat() {
    setBusy(true);
    try {
      const c = await post<SupportConversation>("/api/support/conversations", {});
      go({ name: "chat", id: c.id });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-zinc-50">
      <div className="bg-zinc-950 px-5 pb-8 pt-2 text-white">
        <h2 className="font-display text-2xl font-semibold leading-tight">{first ? `Hey ${first}! ` : "Hey! "}👋</h2>
        <p className="mt-1 text-sm text-zinc-300">Welcome to BlackSync Support. How can we help you today?</p>
      </div>
      <div className="-mt-5 space-y-3 px-4 pb-5">
        <div className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-zinc-900/5">
          <Action icon={<Sparkles className="h-4 w-4" />} title="Chat with AI Support" sub={st?.ai_available === false ? "AI is offline — the team will reply" : "Instant answers, any time"}
            onClick={() => void startChat()} loading={busy} primary />
          <Action icon={<TicketIcon className="h-4 w-4" />} title="Submit a Support Ticket" sub="We'll follow up by ticket" onClick={() => go({ name: "new-ticket" })} />
          <Action icon={<Inbox className="h-4 w-4" />} title="View My Conversations" sub="Chats and tickets" onClick={() => go({ name: "list" })} />
        </div>
        {recent && (
          <button type="button" onClick={() => go({ name: "chat", id: recent.id })}
            className="flex w-full items-center gap-3 rounded-2xl bg-white p-3.5 text-left shadow-sm ring-1 ring-zinc-900/5 hover:bg-zinc-50">
            <ModeIcon conv={recent} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2 text-xs text-zinc-500">
                Recent conversation <span>{timeShort(recent.last_message_at)}</span>
              </div>
              <div className={cn("truncate text-sm", recent.unread ? "font-semibold text-zinc-900" : "text-zinc-700")}>{recent.last_preview || "New conversation"}</div>
            </div>
            {recent.unread && <span className="h-2 w-2 rounded-full bg-brand-500" />}
          </button>
        )}
        <form onSubmit={(e) => { e.preventDefault(); go({ name: "help", q }); }}
          className="rounded-2xl bg-white p-3.5 shadow-sm ring-1 ring-zinc-900/5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-900"><BookOpen className="h-4 w-4 text-brand-500" /> Help Center</div>
          <label className="flex items-center gap-2 rounded-xl bg-zinc-100 px-3 py-2">
            <Search className="h-4 w-4 text-zinc-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search for help" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
          </label>
        </form>
      </div>
    </div>
  );
}

function Action({ icon, title, sub, onClick, loading, primary }: { icon: React.ReactNode; title: string; sub: string; onClick: () => void; loading?: boolean; primary?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={loading}
      className="flex w-full items-center gap-3 border-b border-zinc-100 px-4 py-3.5 text-left last:border-0 hover:bg-zinc-50">
      <span className={cn("flex h-9 w-9 items-center justify-center rounded-xl", primary ? "bg-gradient-to-br from-brand-500 to-brand-600 text-white" : "bg-zinc-100 text-zinc-700")}>
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-zinc-900">{title}</span>
        <span className="block text-xs text-zinc-500">{sub}</span>
      </span>
      <ChevronRight className="h-4 w-4 text-zinc-400" />
    </button>
  );
}

function ModeIcon({ conv }: { conv: SupportConversation }) {
  const human = conv.mode === "human_active";
  return (
    <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full", human ? "bg-emerald-50 text-emerald-600" : "bg-brand-50 text-brand-600")}>
      {human ? <UserRound className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
    </span>
  );
}

// ── Chat ──────────────────────────────────────────────────────────────────────

function Chat({ id, st, go, onSeen }: { id: string; st?: State; go: (v: View) => void; onSeen: () => void }) {
  const { conversation: conv, setConversation, messages, add, error } = useLiveConversation(`/api/support/conversations/${id}`);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<SupportAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const lastTyping = useRef(0);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, streaming, conv?.typing]);

  const lastSeq = messages[messages.length - 1]?.seq ?? 0;
  useEffect(() => {
    if (!lastSeq) return;
    void post(`/api/support/conversations/${id}/read`, { seq: lastSeq }).then(onSeen).catch(() => {});
  }, [id, lastSeq, onSeen]);

  async function send() {
    const body = text.trim();
    if ((!body && !files.length) || sending) return;
    setSending(true);
    setErr(null);
    setText("");
    const atts = files.map((f) => f.id);
    setFiles([]);
    try {
      await streamPost(`/api/support/conversations/${id}/messages?stream=true`, { body, client_id: newClientId(), attachments: atts }, (e) => {
        if (e.type === "message") {
          add([e.message as SupportMessage]);
          if ((e.message as SupportMessage).sender !== "customer") setStreaming(null);
        } else if (e.type === "delta") {
          setStreaming((s) => (s ?? "") + String(e.text));
        } else if (e.type === "dropped") {
          setStreaming(null);
        }
      });
    } catch (e) {
      setErr((e as Error).message);
      setText(body);
    } finally {
      setStreaming(null);
      setSending(false);
    }
  }

  async function escalate() {
    try {
      setConversation(await post<SupportConversation>(`/api/support/conversations/${id}/escalate`));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function attach(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setErr(null);
    try {
      const a = await uploadScreenshot(file);
      setFiles((f) => (f.length >= 3 ? f : [...f, a]));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  function typingPing() {
    if (!conv || (conv.mode !== "human_active" && conv.mode !== "waiting_for_human")) return;
    const n = Date.now();
    if (n - lastTyping.current > 3000) {
      lastTyping.current = n;
      void post(`/api/support/conversations/${id}/typing`).catch(() => {});
    }
  }

  const human = conv?.mode === "human_active";
  const waiting = conv?.mode === "waiting_for_human";
  return (
    <>
      <div className="flex shrink-0 items-center gap-2 border-b border-zinc-100 bg-white px-4 py-2 text-xs">
        {human ? (
          <><span className="h-2 w-2 rounded-full bg-emerald-500" /><span className="font-medium text-zinc-800">Chatting with {conv?.agent_name ?? "the BlackSync team"}</span><span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">Human</span></>
        ) : waiting ? (
          <><span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" /><span className="font-medium text-zinc-800">{st?.staff_online ? "Waiting for the team…" : "Request sent to the team"}</span></>
        ) : conv?.mode === "resolved" ? (
          <span className="text-zinc-500">Resolved — write here to reopen</span>
        ) : (
          <><Sparkles className="h-3.5 w-3.5 text-brand-500" /><span className="font-medium text-zinc-800">BlackSync AI</span><span className="rounded bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700">AI</span>
            <button type="button" onClick={() => void escalate()} className="ml-auto font-medium text-brand-700 hover:text-brand-800">Talk to a person</button></>
        )}
      </div>
      <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto bg-white px-4 py-4">
        {error && <p className="text-center text-xs text-red-600">{error}</p>}
        {!conv && !error && <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-zinc-400" /></div>}
        {messages.map((m) => (
          <Bubble key={m.seq} m={m} viewer="customer" onArticle={(slug) => go({ name: "article", slug })}
            actions={(m.meta.offer_escalation || m.meta.offer_ticket) && m.seq === lastSeq ? (
              <div className="flex flex-wrap gap-1.5">
                {m.meta.offer_escalation && conv?.mode === "ai_active" && (
                  <button type="button" onClick={() => void escalate()} className="rounded-full bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800">Talk to a person</button>
                )}
                {m.meta.offer_ticket && !conv?.ticket_id && (
                  <button type="button" onClick={() => go({ name: "new-ticket", conversationId: id })} className="rounded-full bg-white px-3 py-1.5 text-xs font-medium text-zinc-800 ring-1 ring-zinc-200 hover:bg-zinc-50">Create a ticket</button>
                )}
              </div>
            ) : m.meta.ticket ? (
              <button type="button" onClick={() => go({ name: "ticket", id: m.meta.ticket!.id })} className="text-xs font-medium text-brand-700 underline">View ticket #{m.meta.ticket.number}</button>
            ) : undefined}
          />
        ))}
        {streaming !== null && streaming.length > 0 && (
          <div className="flex flex-col items-start gap-1">
            <div className="flex items-center gap-1.5 px-1 text-[11px] font-medium text-zinc-500"><Sparkles className="h-3 w-3 text-brand-500" /> BlackSync AI</div>
            <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-md bg-zinc-100 px-3.5 py-2.5 text-[13.5px] leading-relaxed text-zinc-900">{cleanAi(streaming)}</div>
          </div>
        )}
        {(streaming === "" || (streaming === null && conv?.typing === "ai" && sending)) && <TypingDots label="BlackSync AI is typing" />}
        {conv?.typing === "agent" && <TypingDots label={`${conv.agent_name ?? "The team"} is typing`} />}
      </div>
      <div className="shrink-0 border-t border-zinc-100 bg-white p-3">
        {err && <p className="mb-2 text-xs text-red-600">{err}</p>}
        {files.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {files.map((f) => (
              <span key={f.id} className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2.5 py-1 text-[11px] text-zinc-700">
                {f.filename}
                <button type="button" onClick={() => setFiles((x) => x.filter((y) => y.id !== f.id))} aria-label="Remove"><X className="h-3 w-3" /></button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-2xl bg-zinc-100 px-3 py-2 focus-within:ring-2 focus-within:ring-brand-500/40">
          <label className="cursor-pointer pb-1 text-zinc-400 hover:text-zinc-700" title="Attach a screenshot">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImagePlus className="h-4 w-4" />}
            <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden" onChange={(e) => { void attach(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          <textarea
            value={text}
            rows={1}
            maxLength={4000}
            onChange={(e) => { setText(e.target.value); typingPing(); }}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
            placeholder={human ? "Message the team…" : "Ask a question…"}
            className="max-h-28 min-h-[24px] flex-1 resize-none bg-transparent py-0.5 text-sm outline-none"
          />
          <button type="button" onClick={() => void send()} disabled={sending || (!text.trim() && !files.length)} aria-label="Send"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-500 text-white transition hover:bg-brand-600 disabled:opacity-40">
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
        <p className="mt-1.5 text-center text-[10px] text-zinc-400">AI answers can be wrong — ask for a person any time.</p>
      </div>
    </>
  );
}

// ── Conversations & tickets ───────────────────────────────────────────────────

function ListView({ tab, go, setTab }: { tab: "chats" | "tickets"; go: (v: View) => void; setTab: (t: "chats" | "tickets") => void }) {
  const { data: convs } = useSWR<{ conversations: SupportConversation[] }>(tab === "chats" ? "/api/support/conversations" : null, fetcher);
  const { data: tickets } = useSWR<{ tickets: SupportTicket[] }>(tab === "tickets" ? "/api/support/tickets" : null, fetcher);
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-zinc-50">
      <div className="flex shrink-0 gap-1 border-b border-zinc-100 bg-white p-2">
        {(["chats", "tickets"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={cn("flex-1 rounded-xl py-2 text-sm font-medium", tab === t ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}>
            {t === "chats" ? "Chats" : "Tickets"}
          </button>
        ))}
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {tab === "chats" && (!convs ? <Spin /> : convs.conversations.length === 0 ? <Empty text="No conversations yet." /> :
          convs.conversations.map((c) => (
            <button key={c.id} type="button" onClick={() => go({ name: "chat", id: c.id })}
              className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-left ring-1 ring-zinc-900/5 hover:bg-zinc-50">
              <ModeIcon conv={c} />
              <div className="min-w-0 flex-1">
                <div className="flex justify-between gap-2 text-[11px] text-zinc-500">
                  <span>{c.mode === "human_active" ? "With the team" : c.mode === "waiting_for_human" ? "Waiting for the team" : c.mode === "resolved" ? "Resolved" : "AI support"}</span>
                  <span>{timeShort(c.last_message_at)}</span>
                </div>
                <div className={cn("truncate text-sm", c.unread ? "font-semibold text-zinc-900" : "text-zinc-700")}>{c.last_preview || "New conversation"}</div>
              </div>
              {c.unread && <span className="h-2 w-2 shrink-0 rounded-full bg-brand-500" />}
            </button>
          )))}
        {tab === "tickets" && (!tickets ? <Spin /> : (
          <>
            <button type="button" onClick={() => go({ name: "new-ticket" })} className="w-full rounded-2xl border border-dashed border-zinc-300 p-3 text-sm font-medium text-zinc-700 hover:bg-white">+ New ticket</button>
            {tickets.tickets.length === 0 ? <Empty text="No tickets yet." /> : tickets.tickets.map((t) => (
              <button key={t.id} type="button" onClick={() => go({ name: "ticket", id: t.id })}
                className="w-full rounded-2xl bg-white p-3 text-left ring-1 ring-zinc-900/5 hover:bg-zinc-50">
                <div className="flex items-center justify-between gap-2 text-[11px] text-zinc-500">
                  <span>#{t.number} · {categoryLabel(t.category)}</span>
                  <StatusPill status={t.status} />
                </div>
                <div className={cn("mt-0.5 truncate text-sm", t.unread ? "font-semibold text-zinc-900" : "text-zinc-800")}>{t.subject}</div>
                <div className="text-[11px] text-zinc-400">Updated {timeShort(t.updated_at)}</div>
              </button>
            ))}
          </>
        ))}
      </div>
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const tone = status === "open" ? "bg-brand-50 text-brand-700" : status === "in_progress" ? "bg-sky-50 text-sky-700"
    : status === "waiting_for_customer" ? "bg-amber-50 text-amber-800" : "bg-zinc-100 text-zinc-600";
  return <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", tone)}>{TICKET_STATUS[status] ?? status}</span>;
}

function NewTicket({ conversationId, done }: { conversationId?: string; done: (id: string) => void }) {
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("technical");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<SupportAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const t = conversationId
        ? await post<SupportTicket>(`/api/support/conversations/${conversationId}/ticket`, { subject, category, description })
        : await post<SupportTicket>("/api/support/tickets", { subject, category, description, attachments: files.map((f) => f.id) });
      done(t.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-xl bg-zinc-100 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand-500/40";
  return (
    <div className="flex-1 space-y-3 overflow-y-auto bg-white p-4">
      {conversationId && <p className="rounded-xl bg-brand-50 px-3 py-2 text-xs text-brand-900">Your chat history will be attached so you don&apos;t have to repeat yourself.</p>}
      <label className="block text-xs font-medium text-zinc-700">Category
        <select value={category} onChange={(e) => setCategory(e.target.value)} className={cn(field, "mt-1")}>
          {TICKET_CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      <label className="block text-xs font-medium text-zinc-700">Subject
        <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} placeholder="Short summary" className={cn(field, "mt-1")} />
      </label>
      <label className="block text-xs font-medium text-zinc-700">What's going on?
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={6} maxLength={8000}
          placeholder="What you expected, what happened, and the agent or campaign involved." className={cn(field, "mt-1 resize-none")} />
      </label>
      {!conversationId && (
        <div>
          <div className="mb-1 text-xs font-medium text-zinc-700">Screenshots (up to 3)</div>
          <div className="flex flex-wrap gap-2">
            {files.map((f) => <AuthImage key={f.id} att={f} />)}
            {files.length < 3 && (
              <label className="flex h-20 w-24 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-zinc-300 text-[11px] text-zinc-500 hover:bg-zinc-50">
                <ImagePlus className="h-4 w-4" /> Add image
                <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (!f) return;
                    try { const a = await uploadScreenshot(f); setFiles((x) => [...x, a]); } catch (er) { setErr((er as Error).message); }
                  }} />
              </label>
            )}
          </div>
        </div>
      )}
      {err && <p className="text-xs text-red-600">{err}</p>}
      <button type="button" disabled={busy || (!conversationId && (subject.trim().length < 3 || description.trim().length < 3))} onClick={() => void submit()}
        className="flex h-11 w-full items-center justify-center gap-2 rounded-full bg-gradient-to-br from-brand-500 to-brand-600 text-sm font-semibold text-white disabled:opacity-40">
        {busy && <Loader2 className="h-4 w-4 animate-spin" />} Submit ticket
      </button>
    </div>
  );
}

function TicketView({ id, onSeen }: { id: string; onSeen: () => void }) {
  const { data, mutate } = useSWR<{ ticket: SupportTicket; replies: TicketReply[] }>(`/api/support/tickets/${id}`, fetcher, { refreshInterval: 15000 });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) onSeen(); }, [data, onSeen]);
  if (!data) return <Spin />;
  const t = data.ticket;
  return (
    <>
      <div className="flex-1 space-y-3 overflow-y-auto bg-white p-4">
        <div>
          <div className="flex items-center justify-between text-[11px] text-zinc-500"><span>#{t.number} · {categoryLabel(t.category)}</span><StatusPill status={t.status} /></div>
          <h3 className="mt-1 text-base font-semibold text-zinc-900">{t.subject}</h3>
          <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-zinc-700">{t.description}</p>
          {!!t.attachments?.length && <div className="mt-2 flex flex-wrap gap-2">{t.attachments.map((a) => <AuthImage key={a.id} att={a} />)}</div>}
        </div>
        {data.replies.map((r) => r.author_kind === "system" ? (
          <p key={r.id} className="text-center text-[11px] text-zinc-400">{r.body} · {timeShort(r.created_at)}</p>
        ) : (
          <div key={r.id} className={cn("rounded-2xl p-3 text-[13px]", r.author_kind === "staff" ? "bg-zinc-100" : "bg-brand-50")}>
            <div className="mb-1 flex justify-between text-[11px] text-zinc-500"><span className="font-medium">{r.author_kind === "staff" ? `${r.author_name ?? "BlackSync team"} · BlackSync` : "You"}</span><span>{timeShort(r.created_at)}</span></div>
            <p className="whitespace-pre-wrap text-zinc-800">{r.body}</p>
          </div>
        ))}
      </div>
      <div className="shrink-0 border-t border-zinc-100 bg-white p-3">
        <div className="flex items-end gap-2 rounded-2xl bg-zinc-100 px-3 py-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} placeholder={t.status === "closed" || t.status === "resolved" ? "Reply to reopen this ticket…" : "Reply…"}
            className="max-h-28 flex-1 resize-none bg-transparent text-sm outline-none" />
          <button type="button" disabled={busy || !text.trim()} aria-label="Send reply"
            onClick={async () => { setBusy(true); try { await post(`/api/support/tickets/${id}/replies`, { body: text }); setText(""); await mutate(); } finally { setBusy(false); } }}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-500 text-white disabled:opacity-40">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Help center ───────────────────────────────────────────────────────────────

function Help({ initial, go }: { initial: string; go: (v: View) => void }) {
  const [q, setQ] = useState(initial);
  const [debounced, setDebounced] = useState(initial);
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(t); }, [q]);
  const { data } = useSWR<{ articles: Article[] }>(`/api/support/articles?q=${encodeURIComponent(debounced)}`, fetcher);
  const groups = new Map<string, Article[]>();
  for (const a of data?.articles ?? []) groups.set(a.category, [...(groups.get(a.category) ?? []), a]);
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-zinc-50">
      <div className="shrink-0 border-b border-zinc-100 bg-white p-3">
        <label className="flex items-center gap-2 rounded-xl bg-zinc-100 px-3 py-2">
          <Search className="h-4 w-4 text-zinc-400" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search for help" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
        </label>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        {!data ? <Spin /> : data.articles.length === 0 ? (
          <Empty text={debounced ? "No articles match. Try other words, or chat with us." : "No articles yet."} />
        ) : [...groups.entries()].map(([cat, arts]) => (
          <div key={cat}>
            {!debounced && <div className="mb-1.5 px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{KB_CATEGORY[cat] ?? cat}</div>}
            <div className="overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-900/5">
              {arts.map((a) => (
                <button key={a.id} type="button" onClick={() => go({ name: "article", slug: a.slug })}
                  className="flex w-full items-center gap-2 border-b border-zinc-100 px-3.5 py-3 text-left last:border-0 hover:bg-zinc-50">
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-zinc-900">{a.title}</span>
                    {a.summary && <span className="block truncate text-xs text-zinc-500">{a.summary}</span>}
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" />
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ArticleView({ slug, go }: { slug: string; go: (v: View) => void }) {
  const { data, error } = useSWR<Article>(`/api/support/articles/${slug}`, fetcher);
  if (error) return <Empty text="This article isn't available." />;
  if (!data) return <Spin />;
  return (
    <div className="flex-1 overflow-y-auto bg-white p-5">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-600">{KB_CATEGORY[data.category] ?? data.category}</div>
      <h3 className="mt-1 text-lg font-semibold text-zinc-900">{data.title}</h3>
      <div className="mt-3 whitespace-pre-wrap text-[13.5px] leading-relaxed text-zinc-700">{data.body}</div>
      <div className="mt-6 rounded-2xl bg-zinc-50 p-4 text-sm">
        <div className="font-medium text-zinc-900">Still need help?</div>
        <button type="button" onClick={async () => { const c = await post<SupportConversation>("/api/support/conversations", {}); go({ name: "chat", id: c.id }); }}
          className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-zinc-900 px-3.5 py-2 text-xs font-medium text-white">
          <LifeBuoy className="h-3.5 w-3.5" /> Chat with support
        </button>
      </div>
    </div>
  );
}

function Spin() {
  return <div className="flex flex-1 justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-zinc-400" /></div>;
}

function Empty({ text }: { text: string }) {
  return <p className="px-4 py-10 text-center text-sm text-zinc-500">{text}</p>;
}
