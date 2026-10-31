import "server-only";
import { cache } from "react";
import { headers } from "next/headers";
import type { Brand } from "./branding";
import { clerkDomainOptions } from "./white-label-clerk";

export const hostBranding = cache(async (): Promise<Brand> => {
  const fallback: Brand = { name: "BlackSync", logo_url: null, custom: false };
  const incoming = await headers();
  const host = incoming.get("host") ?? "";
  const raw = (process.env.BACKEND_ORIGIN ?? "http://localhost:8000").replace(/\/$/, "");
  const origin = raw.includes("://") ? raw : `http://${raw}`;
  try {
    const response = await fetch(`${origin}/api/branding?host=${encodeURIComponent(host.split(":")[0])}`, {
      cache: "no-store", signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return fallback;
    return await response.json() as Brand;
  } catch {
    return fallback;
  }
});

export async function satelliteAuthRedirect(path: "sign-in" | "sign-up"): Promise<string | null> {
  const host = (await headers()).get("host") ?? "";
  const options = clerkDomainOptions(host);
  if (!options.isSatellite || !(await hostBranding()).custom) return null;
  const destination = new URL(path === "sign-in" ? options.signInUrl : options.signUpUrl);
  destination.searchParams.set("redirect_url", `https://${host}/dashboard`);
  return destination.toString();
}
