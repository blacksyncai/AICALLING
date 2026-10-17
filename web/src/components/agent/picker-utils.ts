"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Open/close state for a trigger + popover: click outside and Esc close it, focus returns to the trigger. */
export function usePopover<T extends HTMLElement = HTMLButtonElement>({ defaultOpen = false, dismissOnOutside = true, dismissOnEscape = true }: { defaultOpen?: boolean; dismissOnOutside?: boolean; dismissOnEscape?: boolean } = {}) {
  const [open, setOpen] = useState(defaultOpen);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<T>(null);

  const close = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) requestAnimationFrame(() => triggerRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent | TouchEvent) => {
      if (dismissOnOutside && rootRef.current && !rootRef.current.contains(e.target as Node)) close(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && dismissOnEscape) {
        e.stopPropagation();
        close();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close, dismissOnOutside, dismissOnEscape]);

  return { open, setOpen, close, rootRef, triggerRef };
}

/** Arrow/Home/End/Enter handling for a combobox input driving a listbox of `count` options. */
export function listKeyHandler(
  count: number,
  active: number,
  setActive: (i: number) => void,
  onEnter: (i: number) => void,
) {
  return (e: React.KeyboardEvent) => {
    if (!count) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(active < 0 ? 0 : Math.min(count - 1, active + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(Math.max(0, active - 1));
    } else if (e.key === "Home" && e.ctrlKey) {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End" && e.ctrlKey) {
      e.preventDefault();
      setActive(count - 1);
    } else if (e.key === "PageDown") {
      e.preventDefault();
      setActive(Math.min(count - 1, Math.max(0, active) + 8));
    } else if (e.key === "PageUp") {
      e.preventDefault();
      setActive(Math.max(0, active - 8));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      onEnter(active);
    }
  };
}

const LANG_FALLBACK: Record<string, string> = { multi: "Multilingual" };

/** "es" → "Spanish" (falls back to the code). */
export function languageName(code?: string | null): string {
  if (!code) return "";
  const base = code.toLowerCase().replace("_", "-");
  if (LANG_FALLBACK[base]) return LANG_FALLBACK[base];
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(base) ?? code;
  } catch {
    return code;
  }
}

export const baseLanguage = (code?: string | null) => (code ?? "").toLowerCase().replace("_", "-").split("-")[0];

/** Mirrors backend app/agent/models.py language_mismatch(): unknown or Multilingual never mismatches. */
export function languageMismatch(voiceLanguage?: string | null, agentLanguage?: string | null): boolean {
  const v = baseLanguage(voiceLanguage);
  const a = baseLanguage(agentLanguage);
  if (!v || !a || a === "multi") return false;
  return v !== a;
}

export const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
