import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Pages need a Clerk session. The API (proxied to the backend) verifies the session
// itself, and sign-in, sign-up and invite links must open while signed out.
const isPublic = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)", "/login", "/invite(.*)", "/api/(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (!isPublic(req)) await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    // Always run for Clerk's auto-proxy path
    "/__clerk/:path*",
  ],
};
