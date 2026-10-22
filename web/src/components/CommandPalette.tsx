"use client";

import {
  ArrowRight,
  BarChart3,
  Bot,
  CalendarDays,
  Contact,
  CornerDownLeft,
  LayoutDashboard,
  Megaphone,
  Hash,
  PhoneCall,
  Plus,
  Search,
  Upload,
  UserCog,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import useSWR from "swr";
import { Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import { cn, humanize, timeAgo, outcomeLabel } from "@/lib/utils";

/** Fire this anywhere (e.g. a sidebar button) to open the palette. */
export const OPEN_COMMAND_PALETTE = "open-command-palette";
export const openCommandPalette = () => window.dispatchEvent(new Event(OPEN_COMMAND_PALETTE));

// ── Types ─────────────────────────────────────────────────────────────────────

type SearchResults = {
  contacts: { id: string; name: string; company: string; phone: string }[];
  agents: { id: string; name: string }[];
  campaigns: { id: string; name: string; status: string }[];
  calls: { id: string; contact_name: string; to_phone: string; outcome: string | null; started_at: string | null }[];
};

type Item = {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  href: string;
  keywords?: string;
  /** Search results are already matched by the server, so don't re-filter them. */
  remote?: boolean;
};

type Action = Omit<Item, "id" | "remote"> & { key: string; managersOnly?: boolean };

const ACTIONS: Action[] = [
  { key: "new-agent", group: "Quick actions", label: "New agent", hint: "Set up an AI caller", icon: Plus, href: "/agents", keywords: "create add bot assistant" },
  { key: "import-contacts", group: "Quick actions", label: "Import contacts", hint: "Upload a CSV", icon: Upload, href: "/contacts", keywords: "csv upload leads add" },
  { key: "new-campaign", group: "Quick actions", label: "New campaign", hint: "Call a list of contacts", icon: Megaphone, href: "/campaigns", keywords: "create launch outreach dial" },
  { key: "invite", group: "Quick actions", label: "Invite a teammate", hint: "Add people to your team", icon: UserPlus, href: "/profile?tab=team", keywords: "team member user add colleague", managersOnly: true },
  { key: "go-dashboard", group: "Go to", label: "Dashboard", icon: LayoutDashboard, href: "/dashboard", keywords: "home overview stats" },
  { key: "go-agents", group: "Go to", label: "Agents", icon: Bot, href: "/agents", keywords: "bots assistants" },
  { key: "go-contacts", group: "Go to", label: "Contacts", icon: Contact, href: "/contacts", keywords: "leads people crm" },
  { key: "go-campaigns", group: "Go to", label: "Campaigns", icon: Megaphone, href: "/campaigns", keywords: "outreach" },
  { key: "go-calls", group: "Go to", label: "Call logs", icon: PhoneCall, href: "/calls", keywords: "history recordings transcripts" },
  { key: "go-numbers", group: "Go to", label: "Phone numbers", icon: Hash, href: "/phone-numbers", keywords: "caller id twilio line" },
  { key: "go-meetings", group: "Go to", label: "Meetings", icon: CalendarDays, href: "/meetings", keywords: "booked calendar appointments" },
  { key: "go-analytics", group: "Go to", label: "Analytics", icon: BarChart3, href: "/analytics", keywords: "reports insights performance" },
  { key: "go-profile", group: "Go to", label: "Profile & team", icon: UserCog, href: "/profile", keywords: "account settings billing credits" },
];

const EMPTY_RESULTS: SearchResults = { contacts: [], agents: [], campaigns: [], calls: [] };

// ── Helpers ───────────────────────────────────────────────────────────────────

function useIsMac() {
  const [mac, setMac] = useState(true);
  useEffect(() => {
    setMac(/Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent));
  }, []);
  return mac;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function matchesAction(a: Action, q: string) {
  const hay = `${a.label} ${a.group} ${a.keywords ?? ""}`.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => hay.includes(w));
}

/** Bold the part of `text` that matches what was typed. */
function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (q.length < 1) return <>{text}</>;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <mark className="rounded-[3px] bg-brand-100 px-0.5 text-brand-900">{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  );
}

function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border border-zinc-200 bg-white px-1 font-sans text-[11px] font-medium text-zinc-500 shadow-[0_1px_0_rgba(0,0,0,0.04)]",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

// ── Search button (for the sidebar) ───────────────────────────────────────────

/** A search field look-alike that opens the palette. Drop it in the sidebar. */
export function SearchButton({ className }: { className?: string }) {
  const mac = useIsMac();
  return (
    <button
      type="button"
      onClick={openCommandPalette}
      className={cn(
        "group flex h-9 w-full items-center gap-2 rounded-lg border border-zinc-200 bg-white px-2.5 text-sm text-zinc-500 shadow-xs transition-colors hover:border-zinc-300 hover:text-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
        className,
      )}
      aria-label="Search and quick actions"
      aria-keyshortcuts={mac ? "Meta+K" : "Control+K"}
    >
      <Search className="h-4 w-4 shrink-0 text-zinc-400 group-hover:text-zinc-600" />
      <span className="flex-1 truncate text-left">Search…</span>
      <span className="hidden items-center gap-0.5 sm:flex">
        <Kbd>{mac ? "⌘" : "Ctrl"}</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  );
}

// ── Palette ───────────────────────────────────────────────────────────────────

export function CommandPalette() {
  const { session } = useSession();
  const enabled = !!session?.org;
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_COMMAND_PALETTE, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_COMMAND_PALETTE, onOpen);
    };
  }, [enabled]);

  if (!enabled || !open) return null;
  return <Palette onClose={() => setOpen(false)} manager={canManage(session)} />;
}

function Palette({ onClose, manager }: { onClose: () => void; manager: boolean }) {
  const router = useRouter();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  // Mouse hover only moves the highlight once the pointer actually moves, so a list
  // re-rendering under a stationary cursor doesn't steal the keyboard selection.
  const pointerMoved = useRef(false);

  const q = query.trim();
  const debounced = useDebounced(q, 200);
  const searchKey = debounced.length >= 2 ? `/api/search?q=${encodeURIComponent(debounced)}` : null;
  const { data, isLoading } = useSWR<SearchResults>(searchKey, fetcher, { keepPreviousData: true, revalidateOnFocus: false });
  const results = searchKey ? data ?? EMPTY_RESULTS : EMPTY_RESULTS;
  const searching = q.length >= 2 && (debounced !== q || isLoading);

  // Remember what had focus so we can hand it back on close; lock page scroll.
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    inputRef.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      prev?.focus?.();
    };
  }, []);

  const items = useMemo<Item[]>(() => {
    const actions = ACTIONS.filter((a) => (manager || !a.managersOnly) && (!q || matchesAction(a, q))).map(
      ({ key, managersOnly: _m, ...a }) => ({ ...a, id: `action-${key}` }),
    );
    if (q.length < 2) return actions;
    const found: Item[] = [
      ...results.contacts.map((c) => ({
        id: `contact-${c.id}`,
        group: "Contacts",
        label: c.name || c.phone,
        hint: [c.company, c.phone].filter(Boolean).join(" · "),
        icon: Contact,
        href: `/contacts/${c.id}`,
        remote: true,
      })),
      ...results.agents.map((a) => ({ id: `agent-${a.id}`, group: "Agents", label: a.name, icon: Bot, href: `/agents/${a.id}`, remote: true })),
      ...results.campaigns.map((c) => ({
        id: `campaign-${c.id}`,
        group: "Campaigns",
        label: c.name,
        hint: humanize(c.status),
        icon: Megaphone,
        href: `/campaigns/${c.id}`,
        remote: true,
      })),
      ...results.calls.map((c) => ({
        id: `call-${c.id}`,
        group: "Calls",
        label: c.contact_name,
        hint: [c.outcome ? outcomeLabel(c.outcome) : null, c.started_at ? timeAgo(c.started_at) : null].filter(Boolean).join(" · "),
        icon: PhoneCall,
        href: `/calls/${c.id}`,
        remote: true,
      })),
    ];
    // Records first when searching; matching shortcuts follow.
    return [...found, ...actions];
  }, [q, results, manager]);

  // Reset the highlight whenever the list changes shape.
  useEffect(() => setActive(0), [q, items.length]);

  // Keep the highlighted row in view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const go = useCallback(
    (item: Item | undefined) => {
      if (!item) return;
      onClose();
      router.push(item.href);
    },
    [onClose, router],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    const n = items.length;
    if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) {
      e.preventDefault();
      if (n) setActive((i) => (i + 1) % n);
    } else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) {
      e.preventDefault();
      if (n) setActive((i) => (i - 1 + n) % n);
    } else if (e.key === "Home" && n) {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End" && n) {
      e.preventDefault();
      setActive(n - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(items[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "Tab") {
      // Only the input is focusable inside; keep focus here.
      e.preventDefault();
    }
  };

  const optionId = (i: number) => `${listId}-opt-${i}`;
  const empty = items.length === 0 && !searching;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-zinc-900/40 px-3 pt-[12vh] backdrop-blur-[2px] sm:px-4"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search and quick actions"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="flex max-h-[76vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl ring-1 ring-black/5"
      >
        {/* Input */}
        <div className="flex items-center gap-3 border-b border-zinc-100 px-4">
          {searching ? <Spinner className="h-4 w-4 shrink-0 text-brand-600" /> : <Search className="h-4 w-4 shrink-0 text-zinc-400" />}
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search contacts, agents, campaigns, calls…"
            className="h-14 min-w-0 flex-1 bg-transparent text-[15px] text-zinc-900 outline-none placeholder:text-zinc-400"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={items.length ? optionId(active) : undefined}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
          />
          <button
            type="button"
            onClick={onClose}
            className="hidden rounded-md text-zinc-400 hover:text-zinc-700 sm:block"
            aria-label="Close"
          >
            <Kbd>Esc</Kbd>
          </button>
          <button type="button" onClick={onClose} className="text-sm font-medium text-zinc-500 hover:text-zinc-800 sm:hidden">
            Cancel
          </button>
        </div>

        {/* Results */}
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Results"
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2"
          onMouseMove={() => (pointerMoved.current = true)}
        >
          {empty && (
            <div className="px-4 py-10 text-center">
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-100 text-zinc-400">
                <Search className="h-5 w-5" />
              </div>
              <p className="text-sm font-medium text-zinc-800">No matches for “{q}”</p>
              <p className="mt-1 text-xs text-zinc-500">Try a name, company, phone number or campaign.</p>
            </div>
          )}
          {items.length === 0 && searching && (
            <div className="px-4 py-10 text-center text-sm text-zinc-500">Searching…</div>
          )}
          {items.map((item, i) => {
            const showHeader = i === 0 || items[i - 1].group !== item.group;
            const selected = i === active;
            const Icon = item.icon;
            return (
              <Fragment key={item.id}>
                {showHeader && (
                  <div role="presentation" className={cn("px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-400", i === 0 ? "pt-1.5" : "pt-3")}>
                    {item.group}
                  </div>
                )}
                <div
                  id={optionId(i)}
                  role="option"
                  aria-selected={selected}
                  data-index={i}
                  onMouseMove={() => pointerMoved.current && !selected && setActive(i)}
                  onClick={() => go(item)}
                  className={cn(
                    "flex cursor-pointer select-none items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors",
                    selected ? "bg-zinc-100 text-zinc-900" : "text-zinc-700",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors",
                      selected ? "border-brand-200 bg-brand-50 text-brand-600" : "border-zinc-200 bg-white text-zinc-500",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-baseline sm:gap-2">
                    <span className="truncate font-medium">
                      <Highlight text={item.label} query={q} />
                    </span>
                    {item.hint && (
                      <span className="truncate text-xs text-zinc-500">
                        {item.remote ? <Highlight text={item.hint} query={q} /> : item.hint}
                      </span>
                    )}
                  </span>
                  {selected && (
                    <span className="hidden shrink-0 items-center gap-1 text-xs text-zinc-400 sm:flex">
                      {item.remote ? "Open" : item.group === "Go to" ? "Go" : "Start"}
                      <CornerDownLeft className="h-3.5 w-3.5" />
                    </span>
                  )}
                  {selected && <ArrowRight className="h-4 w-4 shrink-0 text-zinc-400 sm:hidden" />}
                </div>
              </Fragment>
            );
          })}
        </div>

        {/* Footer */}
        <div className="hidden items-center justify-between gap-4 border-t border-zinc-100 bg-zinc-50/70 px-4 py-2 text-xs text-zinc-500 sm:flex">
          <span className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> to move
            </span>
            <span className="flex items-center gap-1">
              <Kbd>↵</Kbd> to open
            </span>
            <span className="flex items-center gap-1">
              <Kbd>Esc</Kbd> to close
            </span>
          </span>
          {q.length === 1 && <span>Type one more letter to search</span>}
        </div>
      </div>
    </div>
  );
}
