import type { NextConfig } from "next";

// Where the FastAPI backend runs. Every /api/* request (except /api/auth/*,
// which is handled by this app) is proxied there, so the browser only ever
// talks to one origin and no CORS setup is needed.
const RAW_ORIGIN = (process.env.BACKEND_ORIGIN ?? "http://localhost:8000").replace(/\/$/, "");
// Hosts with private networking (e.g. Render) hand out a bare host:port.
const BACKEND_ORIGIN = RAW_ORIGIN.includes("://") ? RAW_ORIGIN : `http://${RAW_ORIGIN}`;

// FastAPI collection routes are canonical WITH a trailing slash; Next's
// :path* rewrite strips it, so map the collection roots explicitly.
const COLLECTIONS = ["agents", "campaigns", "calls", "leads", "runs"];

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  // The Docker image runs the standalone server; `next start` hosts don't need it.
  output: process.env.NEXT_STANDALONE ? "standalone" : undefined,
  async rewrites() {
    return [
      ...COLLECTIONS.flatMap((c) => [
        { source: `/api/${c}`, destination: `${BACKEND_ORIGIN}/api/${c}/` },
        { source: `/api/${c}/`, destination: `${BACKEND_ORIGIN}/api/${c}/` },
      ]),
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
      // OAuth discovery for the ChatGPT / Claude connector (served by the API).
      { source: "/.well-known/:path*", destination: `${BACKEND_ORIGIN}/.well-known/:path*` },
    ];
  },
};

export default nextConfig;
