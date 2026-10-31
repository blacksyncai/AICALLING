import type { LucideIcon } from "lucide-react";

/**
 * Full-screen split auth page (adapted from the "full-screen-signup" design): a black story panel
 * with frosted glass stripes and an orange glow on the left, the form on the right.
 *
 * It's a frame only — the form itself (Clerk's <SignIn>/<SignUp>, or the password login) is passed
 * as children, so sign-in keeps Google, phone, password reset and invites.
 */
export function FullScreenSignup({
  logo,
  headline,
  points = [],
  footnote,
  icon: Icon,
  title,
  subtitle,
  children,
}: {
  logo?: React.ReactNode;
  headline: React.ReactNode;
  points?: { icon: LucideIcon; title: string; text: string }[];
  footnote?: React.ReactNode;
  icon?: LucideIcon;
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <main className="flex min-h-screen w-full flex-col bg-white md:flex-row">
      <div className="contents">
        {/* Story panel */}
        <section className="relative overflow-hidden bg-black p-8 text-white md:sticky md:top-0 md:h-screen md:w-1/2 md:p-14">
          {/* frosted glass stripes */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-[2] flex overflow-hidden backdrop-blur-2xl"
          >
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-full w-16 shrink-0 bg-linear-90 from-[#ffffff00] via-[#000000] via-[69%] to-[#ffffff30] opacity-30"
              />
            ))}
          </div>
          {/* orange glow rising from the bottom */}
          <div
            aria-hidden
            className="pointer-events-none absolute -bottom-24 left-1/2 z-[1] h-72 w-72 -translate-x-1/2 rounded-full bg-brand-500"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute -bottom-10 left-1/2 z-[1] h-20 w-32 -translate-x-1/2 rounded-full bg-amber-200"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-[2] bg-linear-to-t from-transparent via-black/60 to-black"
          />

          <div className="relative z-10 flex h-full flex-col gap-8 md:justify-between">
            {logo}
            <div>
              <h2 className="font-display text-2xl font-semibold leading-tight tracking-tight md:text-4xl">
                {headline}
              </h2>
              {points.length > 0 && (
                <ul className="mt-8 hidden space-y-5 md:block">
                  {points.map(({ icon: PointIcon, title: t, text }) => (
                    <li key={t} className="flex gap-3.5">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/[0.08] ring-1 ring-inset ring-white/15">
                        <PointIcon className="h-4.5 w-4.5 text-brand-400" />
                      </span>
                      <span>
                        <span className="block text-sm font-semibold">{t}</span>
                        <span className="mt-0.5 block text-sm text-zinc-300">
                          {text}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {footnote && (
              <div className="hidden text-xs text-zinc-300 md:block">
                {footnote}
              </div>
            )}
          </div>
        </section>

        {/* Form panel */}
        <section className="relative z-10 flex flex-1 flex-col items-center justify-start bg-white px-6 py-8 text-zinc-900 sm:px-8 md:w-1/2 md:flex-none md:justify-center md:py-12">
          <div className="w-full max-w-md">
            <div className="mb-6">
              {Icon && <Icon className="mb-4 h-9 w-9 text-brand-600" />}
              <h1 className="font-display text-3xl font-semibold tracking-tight">
                {title}
              </h1>
              {subtitle && (
                <p className="mt-1.5 text-sm text-zinc-500">{subtitle}</p>
              )}
            </div>
            {children}
          </div>
        </section>
      </div>
    </main>
  );
}
