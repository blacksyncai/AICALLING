"use client";

import { Bot, BookOpen, Lock, Sparkles, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { sessionToken } from "@/lib/clerk";
import { type SupportAttachment, type SupportMessage, cleanAi, timeShort } from "@/lib/support";
import { cn } from "@/lib/utils";

/** Screenshot that loads with the session's auth (plain <img src> can't send it). */
export function AuthImage({ att, staff }: { att: SupportAttachment; staff?: boolean }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    let alive = true;
    (async () => {
      const token = await sessionToken();
      const res = await fetch(`${staff ? "/api/admin/support" : "/api/support"}/attachments/${att.id}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok || !alive) return;
      revoke = URL.createObjectURL(await res.blob());
      setUrl(revoke);
    })();
    return () => {
      alive = false;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [att.id, staff]);
  return url ? (
    <a href={url} target="_blank" rel="noreferrer" className="block">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt={att.filename} className="max-h-48 max-w-full rounded-xl object-cover ring-1 ring-black/5" />
    </a>
  ) : (
    <div className="h-24 w-36 animate-pulse rounded-xl bg-zinc-200/70" />
  );
}

export function TypingDots({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-1 text-xs text-zinc-500">
      <span className="flex gap-1 rounded-2xl bg-zinc-100 px-3 py-2.5">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400" style={{ animationDelay: `${i * 120}ms` }} />
        ))}
      </span>
      {label}
    </div>
  );
}

/**
 * One message. `mine` = the viewer's side: the customer in the widget, BlackSync staff in the inbox.
 */
export function Bubble({ m, viewer, onArticle, actions }: {
  m: SupportMessage;
  viewer: "customer" | "staff";
  onArticle?: (slug: string) => void;
  actions?: React.ReactNode;
}) {
  if (m.sender === "system") {
    return (
      <div className="my-1 flex flex-col items-center gap-2 px-6 text-center">
        <p className="text-xs leading-relaxed text-zinc-500">{m.body}</p>
        {actions}
      </div>
    );
  }
  const mine = viewer === "customer" ? m.sender === "customer" : m.sender === "agent";
  const label = m.sender === "ai" ? "BlackSync AI" : m.sender === "agent" ? (m.author_name ?? "BlackSync team") : (m.author_name ?? "Customer");
  const Icon = m.sender === "ai" ? Sparkles : m.sender === "agent" ? Bot : UserRound;
  return (
    <div className={cn("flex flex-col gap-1", mine ? "items-end" : "items-start")}>
      {!(viewer === "customer" && m.sender === "customer") && (
        <div className={cn("flex items-center gap-1.5 px-1 text-[11px] font-medium", m.internal ? "text-amber-700" : "text-zinc-500")}>
          {m.internal ? <Lock className="h-3 w-3" /> : <Icon className={cn("h-3 w-3", m.sender === "ai" && "text-brand-500")} />}
          {m.internal ? `Internal note · ${label}` : label}
          {m.sender === "ai" && <span className="rounded bg-brand-50 px-1 text-[10px] font-semibold text-brand-700">AI</span>}
          {m.sender === "agent" && !m.internal && <span className="rounded bg-emerald-50 px-1 text-[10px] font-semibold text-emerald-700">Human</span>}
        </div>
      )}
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2.5 text-[13.5px] leading-relaxed",
          m.internal ? "bg-amber-50 text-amber-950 ring-1 ring-amber-200"
            : mine ? "rounded-br-md bg-gradient-to-br from-brand-500 to-brand-600 text-white"
              : "rounded-bl-md bg-zinc-100 text-zinc-900",
        )}
      >
        {m.sender === "ai" ? cleanAi(m.body) : m.body}
        {m.attachments.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {m.attachments.map((a) => <AuthImage key={a.id} att={a} staff={viewer === "staff"} />)}
          </div>
        )}
      </div>
      {!!m.meta.articles?.length && onArticle && (
        <div className="flex max-w-[85%] flex-wrap gap-1.5">
          {m.meta.articles.map((a) => (
            <button key={a.slug} type="button" onClick={() => onArticle(a.slug)}
              className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-zinc-700 ring-1 ring-zinc-200 hover:bg-zinc-50">
              <BookOpen className="h-3 w-3 text-brand-500" /> {a.title}
            </button>
          ))}
        </div>
      )}
      {actions}
      <span className="px-1 text-[10px] text-zinc-400">{timeShort(m.created_at)}</span>
    </div>
  );
}
