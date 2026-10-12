"use client";

import {
  ArrowRight, BarChart3, BookOpen, Bot, CalendarCheck, ChevronLeft, ChevronsUpDown, Coins, Contact, CreditCard, Hash, LayoutDashboard, LogOut, Megaphone, Menu,
  PhoneCall, Plug, Search, UserRound, UserSearch, X,
} from "lucide-react";
import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { canManage, displayName, initials, signOut, switchOrg, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { openCommandPalette } from "./CommandPalette";
import { Logo, LogoMark } from "./Logo";

type NavItem = { href: string; label: string; icon: typeof Bot; managersOnly?: boolean; leadFinder?: boolean; badge?: string };

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
      { href: "/integrations", label: "Integrations", icon: Plug, managersOnly: true, badge: "New" },
    ],
  },
];

function NavLink({
  href, label, icon: Icon, badge, collapsed, onClick, onHover,
}: {
  href: string; label: string; icon: typeof Bot; badge?: string; collapsed: boolean; onClick: () => void;
  onHover: (el: HTMLElement | null, label: string) => void;
}) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      onClick={onClick}
      onMouseEnter={(e) => onHover(e.currentTarget, label)}
      onFocus={(e) => onHover(e.currentTarget, label)}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? label : undefined}
      data-active={active || undefined}
      className={cn(
        "group relative z-10 flex h-9 items-center gap-3 rounded-xl px-3 text-[13px] font-medium transition-colors duration-200",
        collapsed && "justify-center px-0",
        active ? "text-white" : "text-zinc-400 hover:text-zinc-100",
      )}
    >
      <span className="relative flex shrink-0">
        <Icon className={cn("h-[18px] w-[18px] transition-colors", active ? "text-brand-400 drop-shadow-[0_0_6px_rgba(249,115,22,0.6)]" : "text-zinc-500 group-hover:text-zinc-300")} />
        {badge && collapsed && <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-brand-500 shadow-[0_0_6px_rgba(249,115,22,0.9)]" />}
      </span>
      <span className={cn("flex-1 truncate whitespace-nowrap transition-opacity duration-200", collapsed ? "sr-only" : "opacity-100", active && "font-semibold")}>{label}</span>
      {badge && !collapsed && (
        <span className="rounded-full bg-brand-500 px-1.5 py-px text-[10px] font-semibold text-white shadow-[0_0_10px_rgba(249,115,22,0.55)]">{badge}</span>
      )}
    </Link>
  );
}

/** Measures an element's box inside the scrolling nav, for the sliding highlights. */
function boxIn(container: HTMLElement | null, el: HTMLElement | null) {
  if (!container || !el) return null;
  const c = container.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  return { top: r.top - c.top + container.scrollTop, height: r.height };
}

function CreditsPill({ onClick, collapsed }: { onClick: () => void; collapsed: boolean }) {
  const { session } = useSession();
  const org = session?.org;
  if (!org) return null;
  const low = !org.unlimited_credits && org.credits_balance <= 10;
  const value = org.unlimited_credits ? "Unlimited" : org.credits_balance.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return (
    <Link
      href="/billing"
      onClick={onClick}
      title={collapsed ? `Calling credits: ${value}` : undefined}
      aria-label={collapsed ? `Calling credits: ${value}` : undefined}
      className={cn(
        "group flex items-center gap-2.5 rounded-xl px-2 py-2 text-xs transition-colors hover:bg-white/[0.05]",
        collapsed && "justify-center px-0",
      )}
    >
      <span
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-1",
          low ? "bg-amber-400/10 text-amber-300 ring-amber-400/30" : "bg-brand-500/15 text-brand-300 ring-brand-500/30",
        )}
      >
        <Coins className="h-3.5 w-3.5" />
      </span>
      {!collapsed && (
        <>
          <span className="min-w-0 flex-1">
            <span className="block text-zinc-400">Calling credits</span>
            <span className={cn("block font-mono text-[13px] font-medium tabular-nums", low ? "text-amber-300" : "text-white")}>{value}</span>
          </span>
          <ArrowRight className="h-4 w-4 shrink-0 text-zinc-500 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-300" />
        </>
      )}
    </Link>
  );
}

function AccountMenu({ onNavigate, collapsed }: { onNavigate: () => void; collapsed: boolean }) {
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
        <div className={cn("absolute bottom-full z-50 mb-2 rounded-xl border border-zinc-200 bg-white p-1.5 shadow-xl", collapsed ? "left-0 w-60" : "inset-x-0")}>
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
      <div className={cn("flex items-center gap-1", collapsed && "flex-col")}>
        {/* Clerk's account menu: profile photo, sign-in methods, security, sign out. */}
        <span className="flex h-10 w-10 shrink-0 items-center justify-center">
          <UserButton appearance={{ elements: { avatarBox: "h-8 w-8" } }} />
        </span>
        {collapsed ? (
          <button onClick={() => setOpen((v) => !v)} className="rounded-lg p-1.5 text-zinc-500 hover:bg-white/5 hover:text-zinc-200" aria-expanded={open} aria-label="Account menu">
            <ChevronsUpDown className="h-4 w-4" />
          </button>
        ) : (
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
        )}
      </div>
    </div>
  );
}

const COLLAPSE_KEY = "bs-sidebar-collapsed";

export function Sidebar() {
  const [open, setOpen] = useState(false);
  const [collapsedPref, setCollapsedPref] = useState(false);
  const { session } = useSession();
  const pathname = usePathname();
  const manager = canManage(session);
  const close = () => setOpen(false);
  // The mobile drawer is always full width.
  const collapsed = collapsedPref && !open;

  useEffect(() => {
    try {
      setCollapsedPref(localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {}
  }, []);
  const toggle = () =>
    setCollapsedPref((v) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, v ? "0" : "1");
      } catch {}
      return !v;
    });

  // Sliding highlights: a soft pill follows the pointer, the glowing bar follows the active page.
  const listRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ top: number; height: number } | null>(null);
  const [activeBox, setActiveBox] = useState<{ top: number; height: number } | null>(null);
  const [tip, setTip] = useState<{ label: string; top: number; left: number } | null>(null);

  useEffect(() => {
    const measure = () => setActiveBox(boxIn(listRef.current, listRef.current?.querySelector<HTMLElement>("[data-active]") ?? null));
    measure();
    const t = window.setTimeout(measure, 320); // after the width animation
    return () => window.clearTimeout(t);
  }, [pathname, collapsed, session]);

  const onHover = (el: HTMLElement | null, label: string) => {
    setHover(boxIn(listRef.current, el));
    if (collapsed && el) {
      const r = el.getBoundingClientRect();
      setTip({ label, top: r.top + r.height / 2, left: r.right + 12 });
    }
  };
  const clearHover = () => {
    setHover(null);
    setTip(null);
  };

  const nav = (
    <nav className="flex h-full flex-col">
      <div className={cn("flex h-16 items-center", collapsed ? "justify-center px-0" : "px-5")}>
        <Link href="/dashboard" onClick={close} aria-label="BlackSync home" className="flex items-center gap-2.5 text-white">
          <LogoMark className="h-8 w-8 drop-shadow-[0_0_12px_rgba(249,115,22,0.35)]" />
          {!collapsed && <span className="font-display text-[17px] font-semibold tracking-tight">BlackSync</span>}
        </Link>
      </div>
      <div className={cn("pb-2", collapsed ? "px-3" : "px-3")}>
        <button
          type="button"
          onClick={() => {
            close();
            openCommandPalette();
          }}
          aria-label="Search and quick actions"
          title={collapsed ? "Search (Ctrl K)" : undefined}
          className={cn(
            "flex h-9 w-full items-center gap-2 rounded-xl bg-white/[0.04] text-sm text-zinc-500 ring-1 ring-inset ring-white/[0.06] transition-colors hover:bg-white/[0.07] hover:text-zinc-300",
            collapsed ? "justify-center" : "px-3",
          )}
        >
          <Search className="h-4 w-4 shrink-0" />
          {!collapsed && (
            <>
              <span className="flex-1 text-left">Search</span>
              <kbd className="rounded border border-white/10 px-1 font-mono text-[10px] text-zinc-500">⌘K</kbd>
            </>
          )}
        </button>
      </div>
      <div ref={listRef} onMouseLeave={clearHover} className="scroll-thin relative flex-1 overflow-y-auto overflow-x-hidden px-3 py-2">
        {/* Pointer highlight */}
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-3 rounded-xl bg-white/[0.05] transition-all duration-200 ease-out",
            hover ? "opacity-100" : "opacity-0",
          )}
          style={hover ? { top: hover.top, height: hover.height } : undefined}
        />
        {/* Active page: orange glow + neon edge bar */}
        {activeBox && (
          <>
            <span
              aria-hidden
              className="pointer-events-none absolute inset-x-3 rounded-xl bg-gradient-to-r from-brand-500/25 via-brand-500/[0.08] to-transparent ring-1 ring-inset ring-white/[0.04] transition-all duration-300 ease-out"
              style={{ top: activeBox.top, height: activeBox.height }}
            />
            <span
              aria-hidden
              className="pointer-events-none absolute left-0 w-[3px] rounded-r-full bg-brand-500 shadow-[0_0_12px_2px_rgba(249,115,22,0.75)] transition-all duration-300 ease-out"
              style={{ top: activeBox.top + 6, height: activeBox.height - 12 }}
            />
          </>
        )}
        {NAV.map((section, i) => {
          // Lead Finder only where it's on for the account (real estate and home services trials).
          const items = section.items.filter(
            (n) => (!n.managersOnly || manager) && (!n.leadFinder || session?.org?.lead_finder_enabled !== false || session?.user.is_superadmin),
          );
          if (!items.length) return null;
          return (
            <div key={section.title ?? i} className={cn(i > 0 && "mt-4")}>
              {section.title &&
                (collapsed ? (
                  <div className="mx-auto mb-2 h-px w-6 bg-white/10" />
                ) : (
                  <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">{section.title}</div>
                ))}
              <div className="space-y-0.5">
                {items.map((n) => (
                  <NavLink key={n.href} href={n.href} label={n.label} icon={n.icon} badge={n.badge} collapsed={collapsed} onClick={close} onHover={onHover} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <div className={cn("space-y-1 border-t border-white/[0.06] p-3", collapsed && "px-2")}>
        <CreditsPill onClick={close} collapsed={collapsed} />
        <AccountMenu onNavigate={close} collapsed={collapsed} />
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
      <div className={cn("relative z-40 shrink-0 transition-[width] duration-300 ease-out max-lg:w-0", collapsed ? "lg:w-[92px]" : "lg:w-[264px]")}>
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 w-64 overflow-visible bg-zinc-950 transition-[transform,width] duration-300 ease-out",
            "bg-[radial-gradient(380px_240px_at_0%_0%,rgba(249,115,22,0.12),transparent_70%)]",
            "lg:inset-y-3 lg:left-3 lg:translate-x-0 lg:rounded-2xl lg:shadow-[0_20px_50px_-20px_rgba(0,0,0,0.6)] lg:ring-1 lg:ring-white/[0.07]",
            collapsed ? "lg:w-[72px]" : "lg:w-60",
            open ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <button
            type="button"
            onClick={toggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="absolute -right-3 top-6 z-50 hidden h-6 w-6 items-center justify-center rounded-full bg-zinc-900 text-zinc-400 shadow-md ring-1 ring-white/10 transition-colors hover:bg-brand-500 hover:text-white hover:shadow-[0_0_12px_rgba(249,115,22,0.6)] lg:flex"
          >
            <ChevronLeft className={cn("h-3.5 w-3.5 transition-transform duration-300", collapsed && "rotate-180")} />
          </button>
          <div className="h-full overflow-hidden lg:rounded-2xl">{nav}</div>
        </aside>
      </div>
      {tip && collapsed && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-[60] -translate-y-1/2 whitespace-nowrap rounded-lg bg-zinc-900 px-2.5 py-1.5 text-xs font-medium text-white shadow-lg ring-1 ring-white/10"
          style={{ top: tip.top, left: tip.left }}
        >
          {tip.label}
        </div>
      )}
    </>
  );
}
