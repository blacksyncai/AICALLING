"use client";

import { Eye } from "lucide-react";
import { switchOrg, useSession } from "@/lib/session";

/** Shown while a platform admin is working inside someone else's account. */
export function ImpersonationBanner() {
  const { session } = useSession();
  if (!session?.impersonating || !session.org) return null;
  return (
    <div className="sticky top-14 z-20 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-brand-600 px-4 py-2 text-center text-sm text-white lg:top-0">
      <span className="flex items-center gap-2">
        <Eye className="h-4 w-4" />
        Viewing <strong className="font-semibold">{session.org.name}</strong> as an admin
      </span>
      <button
        onClick={() => switchOrg(null, `/admin/accounts/${session.org!.id}`)}
        className="rounded-md bg-white/15 px-2.5 py-0.5 text-xs font-medium hover:bg-white/25"
      >
        Exit to admin portal
      </button>
    </div>
  );
}
