/**
 * Optional single-user login — HMAC-SHA256 signed session cookie, no deps.
 * Disabled entirely when AUTH_PASSWORD is empty. Edge + Node safe.
 */

export const COOKIE_NAME = "closer_session";
export const MAX_AGE_S = 60 * 60 * 24 * 7; // 7 days

export function authEnabled(): boolean {
  return Boolean(process.env.AUTH_PASSWORD);
}

export function validCredentials(email: string, password: string): boolean {
  const wantEmail = (process.env.AUTH_EMAIL ?? "admin@example.com").toLowerCase();
  return email.trim().toLowerCase() === wantEmail && password === process.env.AUTH_PASSWORD;
}

function secret(): string {
  return process.env.AUTH_SECRET ?? `closer-${process.env.AUTH_PASSWORD ?? ""}`;
}

async function key(): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export async function createSessionToken(email: string): Promise<string> {
  const payload = `${email}:${Date.now() + MAX_AGE_S * 1000}`;
  const sig = await crypto.subtle.sign("HMAC", await key(), new TextEncoder().encode(payload));
  return `${btoa(payload)}.${btoa(String.fromCharCode(...new Uint8Array(sig)))}`;
}

export async function verifySessionToken(token: string): Promise<string | null> {
  try {
    const [b64, sigB64] = token.split(".");
    if (!b64 || !sigB64) return null;
    const payload = atob(b64);
    const sig = Uint8Array.from(atob(sigB64), (c) => c.charCodeAt(0));
    const ok = await crypto.subtle.verify("HMAC", await key(), sig, new TextEncoder().encode(payload));
    if (!ok) return null;
    const idx = payload.lastIndexOf(":");
    if (Date.now() > Number(payload.slice(idx + 1))) return null;
    return payload.slice(0, idx);
  } catch {
    return null;
  }
}
