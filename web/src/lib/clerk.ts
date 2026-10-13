// Clerk's prebuilt components, dressed in BlackSync's brand.
export const clerkAppearance = {
  // Hides Clerk's "Development mode" badge while the site runs on a Clerk development instance.
  layout: { unsafe_disableDevelopmentModeWarnings: true },
  variables: {
    colorPrimary: "#dc4a1e",
    colorText: "#1c1917",
    colorTextSecondary: "#78716c",
    colorBackground: "#ffffff",
    colorInputBackground: "#ffffff",
    borderRadius: "0.6rem",
    fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
  },
  elements: {
    card: "shadow-sm border border-zinc-200",
    formButtonPrimary: "bg-brand-600 hover:bg-brand-700 shadow-none",
    footerActionLink: "text-brand-600 hover:text-brand-700",
  },
};

type ClerkSession = { getToken: () => Promise<string | null> };
type ClerkGlobal = {
  loaded?: boolean;
  session?: ClerkSession | null;
  signOut: (opts?: { redirectUrl?: string }) => Promise<void>;
};

/** Clerk's browser instance (set up by <ClerkProvider>), if it has loaded. */
export function clerkInstance(): ClerkGlobal | undefined {
  return typeof window === "undefined" ? undefined : (window as unknown as { Clerk?: ClerkGlobal }).Clerk;
}

/** Resolves once Clerk has loaded in the browser (so its session is known), or after a timeout. */
export async function clerkReady(timeoutMs = 8000): Promise<ClerkGlobal | undefined> {
  if (typeof window === "undefined" || !process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) return undefined;
  const start = Date.now();
  while (!clerkInstance()?.loaded && Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 50));
  }
  return clerkInstance();
}

/** A fresh session token for the API — Clerk refreshes it before it expires. */
export async function sessionToken(): Promise<string | null> {
  try {
    return (await (await clerkReady())?.session?.getToken()) ?? null;
  } catch {
    return null;
  }
}
