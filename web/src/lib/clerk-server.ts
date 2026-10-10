/** Clerk runs once its secret key is set on the server; until then the built-in login is used. */
export function clerkEnabled(): boolean {
  return Boolean(process.env.CLERK_SECRET_KEY);
}
