import { sessionToken } from "@/lib/clerk";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
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
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/")) {
    // Session ended (signed out elsewhere or expired) — back to sign in.
    const next = window.location.pathname + window.location.search;
    window.location.href = `/sign-in?redirect_url=${encodeURIComponent(next)}`;
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      const detail = body.detail ?? body.message;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) message = detail.map((d) => d.msg ?? String(d)).join("; ");
    } catch {
      if (res.status >= 500) message = "Backend unreachable — is the API running on BACKEND_ORIGIN?";
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const fetcher = <T,>(url: string) => api<T>(url);

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const patch = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const del = (path: string) => api<void>(path, { method: "DELETE" });
