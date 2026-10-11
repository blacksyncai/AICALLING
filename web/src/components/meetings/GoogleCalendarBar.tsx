"use client";

import { CalendarCheck2, Loader2, RefreshCw, Unplug } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { del, post } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { GoogleStatus } from "./types";

function GoogleMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

/** Connect / sync / disconnect Google Calendar, shown above the meetings. */
export function GoogleCalendarBar({ status, onChanged }: { status: GoogleStatus | undefined; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<"connect" | "sync" | "disconnect" | null>(null);

  if (!status) return <div className="h-[68px] animate-pulse rounded-2xl bg-zinc-100" />;

  async function connect() {
    setBusy("connect");
    try {
      window.location.href = (await post<{ url: string }>("/api/calendar/google/connect")).url;
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(null);
    }
  }

  async function sync() {
    setBusy("sync");
    try {
      const r = await post<{ synced: number; error: string | null }>("/api/calendar/google/sync");
      if (r.error) toast(r.error, "error");
      else toast(r.synced ? `${r.synced} upcoming meeting${r.synced === 1 ? "" : "s"} on your calendar` : "Nothing new to add — upcoming meetings need a time first");
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Google Calendar? Events already added stay on your calendar.")) return;
    setBusy("disconnect");
    try {
      await del("/api/calendar/google");
      toast("Google Calendar disconnected");
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  const pill = "inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-sm font-medium transition active:scale-[0.98] disabled:opacity-60";

  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-white p-4 shadow-[0_1px_3px_rgba(33,27,24,0.05)] ring-1 ring-zinc-900/[0.06] sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-zinc-200">
          <GoogleMark className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900">
            Google Calendar
            {status.connected && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                <CalendarCheck2 className="h-3 w-3" /> Connected
              </span>
            )}
          </div>
          <p className="truncate text-xs text-zinc-500">
            {status.connected
              ? `${status.email || "Your calendar"} · new and moved meetings are added automatically, guests aren't emailed`
              : status.configured
                ? "See your busy times next to booked meetings and add every meeting to your calendar."
                : "Google sign-in isn't switched on for this workspace yet."}
          </p>
        </div>
      </div>
      {status.can_manage && (
        <div className="flex shrink-0 flex-wrap gap-2">
          {status.connected ? (
            <>
              <button type="button" onClick={() => void sync()} disabled={!!busy} className={cn(pill, "bg-zinc-900 text-white hover:bg-zinc-800")}>
                {busy === "sync" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} Sync now
              </button>
              <button type="button" onClick={() => void disconnect()} disabled={!!busy} className={cn(pill, "bg-zinc-100 text-zinc-700 hover:bg-zinc-200/80")}>
                {busy === "disconnect" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Unplug className="h-3.5 w-3.5" />} Disconnect
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => void connect()}
              disabled={!status.configured || !!busy}
              className={cn(pill, "bg-white text-zinc-800 shadow-sm ring-1 ring-zinc-300 hover:bg-zinc-50")}
            >
              {busy === "connect" ? <Loader2 className="h-4 w-4 animate-spin" /> : <GoogleMark className="h-4 w-4" />} Connect with Google
            </button>
          )}
        </div>
      )}
    </div>
  );
}
