import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

export const WEBSITE_URL = "https://blacksync.ai";

/** A quiet link back to the marketing site (blacksync.ai) from the app (blacksync.si). */
export function WebsiteLink({ className, label = "Visit website" }: { className?: string; label?: string }) {
  return (
    <a
      href={WEBSITE_URL}
      className={cn("inline-flex items-center gap-1 text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-800", className)}
    >
      {label}
      <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
    </a>
  );
}
