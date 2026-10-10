import { Logo } from "@/components/Logo";

/** Centered, branded frame around Clerk's sign-in / sign-up cards. */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 py-10">
      <div className="flex flex-col items-center gap-3 text-center">
        <Logo />
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>
        </div>
      </div>
      {children}
    </main>
  );
}
