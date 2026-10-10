"use client";

import { Bot, LayoutDashboard, LogOut, Megaphone, Menu, PhoneCall, Settings, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { SettingsStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Logo } from "./Logo";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/campaigns", label: "Campaigns", icon: Megaphone },
  { href: "/calls", label: "Call Logs", icon: PhoneCall },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { data: status } = useSWR<SettingsStatus>("/api/settings/status", fetcher, { refreshInterval: 30000 });

  const ready = status?.capabilities;
  const level = !status ? "unknown" : ready?.phone_call ? "phone" : ready?.web_call ? "web" : ready?.chat_test ? "chat" : "none";

  const nav = (
    <nav className="flex h-full flex-col">
      <div className="flex h-14 items-center px-5">
        <Link href="/dashboard" onClick={() => setOpen(false)}>
          <Logo className="text-white" />
        </Link>
      </div>
      <div className="flex-1 space-y-0.5 px-3 py-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active ? "bg-white/10 text-white" : "text-zinc-400 hover:bg-white/5 hover:text-white",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </div>
      <div className="space-y-2 border-t border-white/10 p-3">
        <Link href="/settings" onClick={() => setOpen(false)} className="block rounded-lg bg-white/5 px-3 py-2.5 text-xs hover:bg-white/10">
          <div className="flex items-center gap-2 font-medium text-white">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                level === "phone" && "bg-emerald-400",
                level === "web" && "bg-sky-400",
                level === "chat" && "bg-amber-400",
                (level === "none" || level === "unknown") && "bg-zinc-500",
              )}
            />
            {level === "phone" && "Phone calling ready"}
            {level === "web" && "Voice testing ready"}
            {level === "chat" && "Chat testing only"}
            {level === "none" && "Add API keys to start"}
            {level === "unknown" && "Backend offline"}
          </div>
          <div className="mt-0.5 text-zinc-400">View setup →</div>
        </Link>
        <button
          onClick={async () => {
            await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
            window.location.href = "/login";
          }}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-zinc-400 hover:bg-white/5 hover:text-white"
        >
          <LogOut className="h-4 w-4" /> Sign out
        </button>
      </div>
    </nav>
  );

  return (
    <>
      <div className="fixed inset-x-0 top-0 z-40 flex h-14 items-center justify-between bg-zinc-950 px-4 lg:hidden">
        <Logo className="text-white" />
        <button onClick={() => setOpen((v) => !v)} className="rounded-md p-2 text-zinc-300" aria-label="Menu">
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>
      <div className="h-14 lg:hidden" />
      {open && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setOpen(false)} />}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-60 bg-zinc-950 transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {nav}
      </aside>
    </>
  );
}
