import { NextRequest, NextResponse } from "next/server";
import { COOKIE_NAME, MAX_AGE_S, createSessionToken, validCredentials } from "@/lib/auth";

export async function POST(req: NextRequest) {
  const { email = "", password = "" } = await req.json().catch(() => ({}));
  if (!validCredentials(email, password)) {
    return NextResponse.json({ detail: "Wrong email or password" }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE_NAME, await createSessionToken(email), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: MAX_AGE_S,
    path: "/",
  });
  return res;
}
