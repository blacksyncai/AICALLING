"use client";

import {
  BarChart3, BookOpen, Bot, CalendarCheck, ChevronsUpDown, Coins, Contact, CreditCard, Hash, LayoutDashboard, LogOut, Megaphone, Menu, PhoneCall, Plug,
  UserRound, UserSearch, X,
} from "lucide-react";
import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { canManage, displayName, initials, signOut, switchOrg, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { SearchButton } from "./CommandPalette";
import { Logo } from "./Logo";

type NavItem = { href: string; label: string; icon: typeof Bot; managersOnly?: boolean; leadFinder?: boolean };

const NAV: { title: string | null; items: NavItem[] }[] = [
  { title: null, items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }] },
  {
    title: "Build",
    items: [
      { href: "/agents", label: "Agents", icon: Bot },
      { href: "/knowledge", label: "Knowledge", icon: BookOpen },
      { href: "/phone-numbers", label: "Phone Numbers", icon: Hash },
    ],
  },
  {
    title: "Reach",
    items: [
      { href: "/contacts", label: "Contacts", icon: Contact },
      { href: "/lead-finder", label: "Lead Finder", icon: UserSearch, leadFinder: true },
      { href: "/campaigns", label: "Campaigns", icon: Megaphone },
    ],
  },
  {
    title: "Results",
    items: [
      { href: "/calls", label: "Call Logs", icon: PhoneCall },
      { href: "/meetings", label: "Meetings", icon: CalendarCheck },
      { href: "/analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
  {
    title: "Account",
    items: [
      { href: "/billing", label: "Billing & Usage", icon: CreditCard },
      { href: "/integrations", label: "Integrations", icon: Plug, managersOnly: true },
    ],
  },
];

function NavLink({ href, label, icon: Icon, onClick }: { href: string; label: string; icon: typeof Bot; onClick: () => void }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg px-3 py-[7px] text-[13px] font-medium transition-colors",
        active
          ? "bg-gradient-to-r from-white/[0.11] to-white/[0.04] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]"
          : "text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-100",
      )}
    >
      {active && <span className="absolute inset-y-1.5 left-0 w-[3px] rounded-full bg-brand-500 shadow-[0_0_10px_rgba(236,101,60,0.7)]" />}
      <Icon className={cn("h-4 w-4 transition-colors", active ? "text-brand-400" : "text-zinc-500 group-hover:text-zinc-300")} />
      {label}
    </Link>
  );
}

function CreditsPill({ onClick }: { onClick: () => void }) {
  const { session } = useSession();
  const org = session?.org;
  if (!org) return null;
  const low = !org.unlimited_credits && org.credits_balance <= 10;
  return (
    <Link
      href="/billing"
      onClick={onClick}
      className="flex items-center justify-between rounded-lg bg-white/[0.04] px-3 py-2.5 text-xs ring-1 ring-inset ring-white/[0.06] transition-colors hover:bg-white/[0.08]"
    >
      <span className="flex items-center gap-2 text-zinc-400">
        <Coins className={cn("h-4 w-4", low ? "text-amber-400" : "text-brand-400")} />
        Calling credits
      </span>
      <span className={cn("font-mono font-medium tabular-nums", low ? "text-amber-300" : "text-white")}>
        {org.unlimited_credits ? "Unlimited" : org.credits_balance.toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </span>
    </Link>
  );
}

function AccountMenu({ onNavigate }: { onNavigate: () => void }) {
  const { session } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!session) return <div className="h-12 animate-pulse rounded-lg bg-white/5" />;
  const name = displayName(session.user);
  const otherOrgs = session.memberships.filter((m) => m.org_id !== session.org?.id);
  const item = "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-zinc-700 hover:bg-zinc-100";

  return (
    <div ref={ref} className="relative">
      {open && (
        <div className="absolute inset-x-0 bottom-full mb-2 rounded-xl border border-zinc-200 bg-white p-1.5 shadow-xl">
          <div className="px-2.5 py-2">
            <div className="truncate text-sm font-medium text-zinc-900">{name}</div>
            <div className="truncate text-xs text-zinc-500">{session.user.email}</div>
          </div>
          <div className="my-1 h-px bg-zinc-100" />
          <Link href="/profile" className={item} onClick={() => { setOpen(false); onNavigate(); }}>
            <UserRound className="h-4 w-4 text-zinc-400" /> Profile & team
          </Link>
          {otherOrgs.length > 0 && (
            <>
              <div className="my-1 h-px bg-zinc-100" />
              <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium uppercase tracking-wide text-zinc-400">Switch account</div>
              {otherOrgs.map((m) => (
                <button key={m.org_id} className={item} onClick={() => switchOrg(m.org_id)}>
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-zinc-100 text-[10px] font-semibold text-zinc-600">
                    {initials(m.org_name)}
                  </span>
                  <span className="truncate">{m.org_name}</span>
                </button>
              ))}
            </>
          )}
          <div className="my-1 h-px bg-zinc-100" />
          <button className={item} onClick={signOut}>
            <LogOut className="h-4 w-4 text-zinc-400" /> Sign out
          </button>
        </div>
      )}
      <div className="flex items-center gap-1">
        {/* Clerk's account menu: profile photo, sign-in methods, security, sign out. */}
        <span className="flex h-10 w-10 shrink-0 items-center justify-center">
          <UserButton appearance={{ elements: { avatarBox: "h-8 w-8" } }} />
        </span>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-white/5"
          aria-expanded={open}
          aria-label="Account menu"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-white">{name}</span>
            <span className="block truncate text-xs text-zinc-400">{session.org?.name ?? "No account"}</span>
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 text-zinc-500" />
        </button>
      </div>
    </div>
  );
}

export function Sidebar() {
  const [open, setOpen] = useState(false);
  const { session } = useSession();
  const manager = canManage(session);
  const close = () => setOpen(false);

  const nav = (
    <nav className="flex h-full flex-col">
      <div className="flex h-14 items-center px-5">
        <Link href="/dashboard" onClick={close}>
          <Logo className="text-white" />
        </Link>
      </div>
      <div className="px-3 pb-2">
        <SearchButton className="w-full" />
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto px-3 py-2">
        {NAV.map((section, i) => {
          // Lead Finder only where it's on for the account (real estate and home services trials).
          const items = section.items.filter(
            (n) => (!n.managersOnly || manager) && (!n.leadFinder || session?.org?.lead_finder_enabled !== false || session?.user.is_superadmin),
          );
          if (!items.length) return null;
          return (
            <div key={section.title ?? i} className={cn(i > 0 && "mt-4")}>
              {section.title && (
                <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">{section.title}</div>
              )}
              <div className="space-y-0.5">
                {items.map((n) => (
                  <NavLink key={n.href} href={n.href} label={n.label} icon={n.icon} onClick={close} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <div className="space-y-2 border-t border-white/10 p-3">
        <CreditsPill onClick={close} />
        <AccountMenu onNavigate={close} />
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
      {open && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={close} />}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-60 border-r border-white/[0.06] bg-zinc-950 bg-[radial-gradient(420px_220px_at_0%_0%,rgba(236,101,60,0.10),transparent_70%)] transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {nav}
      </aside>
    </>
  );
}
