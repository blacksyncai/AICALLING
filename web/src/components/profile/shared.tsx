"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { cn } from "@/lib/utils";
import type { Role } from "@/lib/types";

export const ROLE_TONE: Record<Role | "superadmin", "brand" | "blue" | "gray" | "violet"> = {
  owner: "brand",
  admin: "blue",
  member: "gray",
  superadmin: "violet",
};

export const ROLE_INFO: { role: Role; label: string; description: string }[] = [
  { role: "owner", label: "Owner", description: "Everything, including transferring ownership." },
  { role: "admin", label: "Admin", description: "Manage the team, integrations and settings." },
  { role: "member", label: "Member", description: "Agents, contacts, campaigns and calls." },
];

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  const text = ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
  return (
    <span
      className={cn(
        "brand-gradient flex shrink-0 items-center justify-center rounded-full font-semibold text-white",
        size === "sm" && "h-8 w-8 text-xs",
        size === "md" && "h-9 w-9 text-xs",
        size === "lg" && "h-14 w-14 text-lg",
      )}
    >
      {text}
    </span>
  );
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

export function CopyButton({ text, label = "Copy", className }: { text: string; label?: string; className?: string }) {
  const toast = useToast();
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        if (await copyText(text)) {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } else toast("Couldn't copy — select the text and copy it manually", "error");
      }}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-50",
        className,
      )}
    >
      {done ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
      {done ? "Copied" : label}
    </button>
  );
}
