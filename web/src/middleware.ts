import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";
import { clerkDomainOptions } from "@/lib/white-label-clerk";

// Pages need a session. The API (proxied to the backend) verifies the session itself,
// and sign-in, sign-up and invite links must open while signed out.
const isPublic = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)", "/login", "/invite(.*)", "/pricing", "/terms", "/connect/help", "/.well-known/(.*)", "/api/(.*)"]);

// New visitors land on sign-up (existing customers tap "Sign in" there); other pages go to sign-in.
const isFrontDoor = createRouteMatcher(["/", "/dashboard"]);

function forwardRequest(req: NextRequest) {
  const headers = new Headers(req.headers);
  headers.set("x-forwarded-host", req.headers.get("host") ?? req.nextUrl.host);
  return NextResponse.next({ request: { headers } });
}

const withClerk = clerkMiddleware(async (auth, req) => {
  if (isPublic(req)) return forwardRequest(req);
  if (isFrontDoor(req) && !(await auth()).userId) {
    const url = req.nextUrl.clone();
    url.pathname = "/sign-up";
    url.search = "";
    return NextResponse.redirect(url);
  }
  await auth.protect();
  return forwardRequest(req);
}, req => clerkDomainOptions(req.headers.get("host") ?? req.nextUrl.host));

// Until CLERK_SECRET_KEY is set, fall back to the built-in session cookie.
function withPasswordLogin(req: NextRequest) {
  if (isPublic(req) || req.cookies.get("bs_session")?.value) return forwardRequest(req);
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  return NextResponse.redirect(url);
}

export default process.env.CLERK_SECRET_KEY ? withClerk : withPasswordLogin;

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    // Always run for Clerk's auto-proxy path
    "/__clerk/:path*",
  ],
};
