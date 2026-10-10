"use client";

import { createContext, useContext, type ReactNode } from "react";
import useSWR, { type KeyedMutator } from "swr";
import { fetcher, post } from "@/lib/api";
import { clerkInstance } from "@/lib/clerk";
import type { Session } from "@/lib/types";

type SessionCtx = {
  session: Session | undefined;
  loading: boolean;
  mutate: KeyedMutator<Session>;
};

const Ctx = createContext<SessionCtx>({ session: undefined, loading: true, mutate: (async () => undefined) as never });

export function SessionProvider({ children }: { children: ReactNode }) {
  const { data, isLoading, mutate } = useSWR<Session>("/api/auth/me", fetcher, { revalidateOnFocus: true });
  return <Ctx.Provider value={{ session: data, loading: isLoading, mutate }}>{children}</Ctx.Provider>;
}

/** The signed-in user, the account they're working in, and their role there. */
export const useSession = () => useContext(Ctx);

export function canManage(session: Session | undefined): boolean {
  if (!session) return false;
  return session.user.is_superadmin || ["owner", "admin", "superadmin"].includes(session.role);
}

/** Work inside another account (super-admins: any account; null returns to your own). */
export async function switchOrg(orgId: string | null, goTo = "/dashboard") {
  await post<Session>("/api/auth/switch-org", { org_id: orgId });
  // Every cached list belongs to the old account, so start clean.
  window.location.href = goTo;
}

export async function signOut() {
  // Clear the built-in session too, for setups not (yet) using Clerk.
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  const clerk = clerkInstance();
  if (clerk?.session) await clerk.signOut({ redirectUrl: "/sign-in" });
  else window.location.href = "/sign-in";
}

export function displayName(u: { first_name: string; last_name: string; email: string }): string {
  return `${u.first_name} ${u.last_name}`.trim() || u.email;
}

export function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}
