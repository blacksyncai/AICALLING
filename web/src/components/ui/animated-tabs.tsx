"use client";

import React, { useState, useRef, useEffect } from "react";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";

export interface AnimatedTab<T extends string = string> {
  id: T;
  label: string;
  icon?: React.ReactNode;
  content?: React.ReactNode;
}

interface AnimatedTabsProps<T extends string = string> {
  tabs?: AnimatedTab<T>[];
  defaultTab?: T;
  /** Controlled mode: the active tab and its setter. */
  value?: T;
  onChange?: (id: T) => void;
  /** "dark" is the original glassy look; "light" matches BlackSync's warm neutrals. */
  variant?: "dark" | "light";
  /** Shared-layout id for the sliding highlight — unique per tab bar on a page. */
  layoutId?: string;
  className?: string;
}

const defaultTabs: AnimatedTab[] = [
  {
    id: "tab1",
    label: "Tab 1",
    content: (
      <div className="grid h-full w-full grid-cols-2 gap-4">
        <img
          src="https://images.unsplash.com/photo-1497366216548-37526070297c?w=800&q=80"
          alt="Office"
          className="!m-0 mt-0 h-60 w-full rounded-lg border-none object-cover shadow-[0_0_20px_rgba(0,0,0,0.2)]"
        />
        <div className="flex flex-col gap-y-2">
          <h2 className="!m-0 mb-0 mt-0 text-2xl font-bold text-white">Tab 1</h2>
          <p className="mt-0 text-sm text-gray-200">Lorem ipsum dolor sit amet consectetur adipisicing elit. Quisquam, quos.</p>
        </div>
      </div>
    ),
  },
  {
    id: "tab2",
    label: "Tab 2",
    content: (
      <div className="grid h-full w-full grid-cols-2 gap-4">
        <img
          src="https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=800&q=80"
          alt="Team"
          className="!m-0 mt-0 h-60 w-full rounded-lg border-none object-cover shadow-[0_0_20px_rgba(0,0,0,0.2)]"
        />
        <div className="flex flex-col gap-y-2">
          <h2 className="!m-0 mb-0 mt-0 text-2xl font-bold text-white">Tab 2</h2>
          <p className="mt-0 text-sm text-gray-200">Lorem ipsum dolor sit amet consectetur adipisicing elit. Quisquam, quos.</p>
        </div>
      </div>
    ),
  },
  {
    id: "tab3",
    label: "Tab 3",
    content: (
      <div className="grid h-full w-full grid-cols-2 gap-4">
        <img
          src="https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=800&q=80"
          alt="Building"
          className="!m-0 mt-0 h-60 w-full rounded-lg border-none object-cover shadow-[0_0_20px_rgba(0,0,0,0.2)]"
        />
        <div className="flex flex-col gap-y-2">
          <h2 className="!m-0 mb-0 mt-0 text-2xl font-bold text-white">Tab 3</h2>
          <p className="mt-0 text-sm text-gray-200">Lorem ipsum dolor sit amet consectetur adipisicing elit. Quisquam, quos.</p>
        </div>
      </div>
    ),
  },
];

/** Just the tab bar with the sliding highlight (use with your own content). */
export function AnimatedTabList<T extends string>({
  tabs,
  value,
  onChange,
  variant = "dark",
  layoutId = "active-tab",
  className,
  swipeHint = false,
}: {
  tabs: AnimatedTab<T>[];
  value: T;
  onChange: (id: T) => void;
  variant?: "dark" | "light";
  layoutId?: string;
  className?: string;
  swipeHint?: boolean;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  useEffect(() => {
    if (!swipeHint) return;
    const el = scroller.current;
    if (!el) return;
    const update = () => setMore(el.scrollWidth - el.clientWidth - el.scrollLeft > 8);
    const observer = new ResizeObserver(update); observer.observe(el);
    el.addEventListener("scroll", update, { passive: true }); update();
    return () => { observer.disconnect(); el.removeEventListener("scroll", update); };
  }, [swipeHint]);
  const light = variant === "light";
  return (
    <div className="relative min-w-0">
    <div
      ref={scroller}
      role="tablist"
      className={cn(
        "flex gap-1 rounded-xl p-1",
        light
          ? "border border-zinc-200/80 bg-zinc-100/80 shadow-[inset_0_1px_2px_rgba(33,27,24,0.06)]"
          : "flex-wrap bg-[#11111198] backdrop-blur-sm",
        className,
      )}
    >
      {tabs.map((tab) => {
        const active = value === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onKeyDown={(event) => {
              const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
              if (!keys.includes(event.key)) return;
              event.preventDefault();
              const index = tabs.findIndex((item) => item.id === tab.id);
              const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
              const button = scroller.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next];
              button?.focus();
              if (swipeHint) button?.scrollIntoView({ block: "nearest", inline: "nearest" });
              onChange(tabs[next].id);
            }}
            onClick={(event) => {
              onChange(tab.id);
              if (swipeHint) event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
            }}
            className={cn(
              "relative flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-brand-500",
              light ? (active ? "text-zinc-900" : "text-zinc-500 hover:text-zinc-800") : "text-white",
            )}
          >
            {active && (
              <motion.div
                layoutId={layoutId}
                className={cn(
                  "absolute inset-0 !rounded-lg",
                  light
                    ? "bg-white shadow-[0_1px_2px_rgba(33,27,24,0.08),0_4px_12px_-4px_rgba(33,27,24,0.12)] ring-1 ring-zinc-200/70"
                    : "bg-[#111111d1] shadow-[0_0_20px_rgba(0,0,0,0.2)] backdrop-blur-sm",
                )}
                transition={{ type: "spring", duration: 0.6 }}
              />
            )}
            {tab.icon && <span className={cn("relative z-10", light && active && "text-brand-600")}>{tab.icon}</span>}
            <span className="relative z-10">{tab.label}</span>
          </button>
        );
      })}
    </div>
    {swipeHint && more && <span aria-hidden="true" className="pointer-events-none absolute right-0 top-0 flex h-full w-8 items-center justify-end rounded-r-xl bg-gradient-to-l from-zinc-800 to-transparent pr-1 text-white sm:hidden">›</span>}
    </div>
  );
}

/** Content that blurs/slides in when the active tab changes — give it `key={activeTab}`. */
export function AnimatedTabPanel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, scale: 0.98, x: -10, filter: "blur(8px)" }}
      animate={{ opacity: 1, scale: 1, x: 0, filter: "blur(0px)" }}
      transition={{ duration: 0.4, ease: "circInOut", type: "spring" }}
    >
      {children}
    </motion.div>
  );
}

const AnimatedTabs = <T extends string = string>({
  tabs = defaultTabs as AnimatedTab<T>[],
  defaultTab,
  value,
  onChange,
  variant = "dark",
  layoutId,
  className,
}: AnimatedTabsProps<T>) => {
  const [internal, setInternal] = useState<T>(defaultTab || tabs[0]?.id);
  const activeTab = value ?? internal;
  const select = (id: T) => {
    if (value === undefined) setInternal(id);
    onChange?.(id);
  };

  if (!tabs?.length) return null;
  const active = tabs.find((t) => t.id === activeTab);

  return (
    <div className={cn("flex w-full max-w-lg flex-col gap-y-1", className)}>
      <AnimatedTabList tabs={tabs} value={activeTab} onChange={select} variant={variant} layoutId={layoutId} />
      <div
        className={cn(
          "h-full min-h-60 rounded-xl border p-4",
          variant === "light"
            ? "border-zinc-200 bg-white text-zinc-900"
            : "bg-[#11111198] text-white shadow-[0_0_20px_rgba(0,0,0,0.2)] backdrop-blur-sm",
        )}
      >
        {active && <AnimatedTabPanel key={active.id}>{active.content}</AnimatedTabPanel>}
      </div>
    </div>
  );
};

export { AnimatedTabs };
