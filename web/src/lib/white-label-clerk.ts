/** Shared by the server layout and middleware. */
export function clerkDomainOptions(host: string) {
  const raw = process.env.WHITE_LABEL_PRIMARY_ORIGIN;
  if (!raw) return {};
  let primary: URL;
  try { primary = new URL(raw); } catch { return {}; }
  if (primary.protocol !== "https:" || primary.username || primary.password || primary.search || primary.hash
    || !["", "/"].includes(primary.pathname)) return {};
  const hostname = host.split(":")[0].toLowerCase();
  if (!hostname || hostname === primary.hostname) return {};
  return {
    isSatellite: true as const,
    domain: hostname,
    signInUrl: `${primary.origin}/sign-in`,
    signUpUrl: `${primary.origin}/sign-up`,
  };
}
