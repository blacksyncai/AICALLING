import { sessionToken } from "@/lib/clerk";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body: Record<string, unknown> = {}) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  // Clerk session tokens are short-lived; send a fresh one with every request.
  const token = await sessionToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  // Signed out (or the session expired) — back to sign in. A Clerk session that the API
  // rejected would just bounce straight back here, so only redirect without one.
  if (res.status === 401 && typeof window !== "undefined" && !token && !path.startsWith("/api/auth/")) {
    const next = window.location.pathname + window.location.search;
    window.location.href = `/sign-in?redirect_url=${encodeURIComponent(next)}`;
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    let parsed: Record<string, unknown> = {};
    try {
      const body = await res.json();
      parsed = body && typeof body === "object" ? body : {};
      const detail = body.detail ?? body.message;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) message = detail.map((d) => d.msg ?? String(d)).join("; ");
    } catch {
      if (res.status >= 500) message = "Backend unreachable — is the API running on BACKEND_ORIGIN?";
    }
    throw new ApiError(res.status, message, parsed);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const fetcher = <T,>(url: string) => api<T>(url);

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const patch = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const put = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const del = (path: string) => api<void>(path, { method: "DELETE" });
