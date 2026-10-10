import type { NextConfig } from "next";

// Where the FastAPI backend runs. Every /api/* request (except /api/auth/*,
// which is handled by this app) is proxied there, so the browser only ever
// talks to one origin and no CORS setup is needed.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

// FastAPI collection routes are canonical WITH a trailing slash; Next's
// :path* rewrite strips it, so map the collection roots explicitly.
const COLLECTIONS = ["agents", "campaigns", "calls", "leads", "runs"];

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  output: "standalone",
  async rewrites() {
    return [
      ...COLLECTIONS.flatMap((c) => [
        { source: `/api/${c}`, destination: `${BACKEND_ORIGIN}/api/${c}/` },
        { source: `/api/${c}/`, destination: `${BACKEND_ORIGIN}/api/${c}/` },
      ]),
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
    ];
  },
};

export default nextConfig;
