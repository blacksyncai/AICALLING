import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { WebsiteLink } from "@/components/WebsiteLink";
import { TERMS_EFFECTIVE, TERMS_VERSION } from "@/lib/terms";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "BlackSync AI Terms of Service & Subscription Agreement.",
};

type Section = { title: string; body: (string | string[])[] };

const SECTIONS: Section[] = [
  {
    title: "Services",
    body: [
      "BlackSync AI provides an AI-powered calling and sales automation platform, including voice agents, outbound and inbound campaigns, lead management, integrations, and related features.",
      "Features and usage allowances vary by subscription plan and are displayed within the application.",
    ],
  },
  {
    title: "Subscriptions & Billing",
    body: [
      "Paid subscriptions are billed automatically on a recurring basis at the price and billing interval selected during checkout.",
      "Subscriptions are month-to-month unless otherwise specified. You may cancel at any time directly within the application before your next billing date. Cancellation prevents future renewals, and access continues through the current paid billing period.",
      "Subscription payments are nonrefundable except where required by law.",
    ],
  },
  {
    title: "Credits & Additional Purchases",
    body: [
      "AI calling credits are consumed based on connected conversation time and the selected AI model. Applicable rates are displayed within the platform.",
      "Unanswered calls do not consume conversational credits. Additional credits, phone numbers, and lead lookups may be purchased separately at the prices displayed before purchase.",
      "Monthly credit allowances reset each billing cycle unless otherwise specified. Unused monthly credits do not roll over.",
    ],
  },
  {
    title: "Acceptable Use",
    body: [
      "You agree not to use BlackSync AI for:",
      [
        "Fraud, scams, phishing, impersonation, or deceptive activities.",
        "Harassment, unlawful telemarketing, or unauthorized calling.",
        "Violations of applicable privacy, consent, consumer protection, or telecommunications laws.",
        "Attempts to compromise, exploit, or misuse the platform.",
      ],
      "You are responsible for ensuring that your calling lists, campaigns, recordings, and communications comply with applicable laws, including consent, do-not-call, and disclosure requirements.",
    ],
  },
  {
    title: "Account Suspension",
    body: [
      "BlackSync AI reserves the right to suspend, restrict, or deactivate accounts that violate these terms, present security risks, involve suspected fraudulent activity, or threaten the platform or its users.",
      "Where appropriate, we may provide notice and an opportunity to resolve the issue.",
    ],
  },
  {
    title: "Data & Privacy",
    body: [
      "You retain ownership of the customer data and lead lists you upload.",
      "BlackSync AI may process this information as necessary to provide its services, subject to our Privacy Policy. You are responsible for having the necessary rights and permissions to upload and process such data.",
    ],
  },
  {
    title: "Service Availability & Liability",
    body: [
      "We work to maintain a reliable platform but do not guarantee uninterrupted availability or specific business results.",
      "To the extent permitted by applicable law, BlackSync AI’s liability for claims relating to the service is limited to the subscription fees paid during the three months preceding the claim.",
    ],
  },
  {
    title: "Changes to Terms",
    body: [
      "We may update these terms as the platform evolves. Material changes will be communicated through the application or by email before taking effect.",
      "Continued use following the effective date of updated terms constitutes acceptance where permitted by law.",
    ],
  },
];

/** Public Terms of Service (no sign-in). The version shown is the one checkout records. */
export default function TermsPage() {
  return (
    <main className="app-canvas min-h-screen">
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-8 sm:py-14">
        <div className="mb-10 flex items-center justify-between gap-4">
          <Link href="/sign-in" aria-label="BlackSync" className="text-zinc-900">
            <Logo />
          </Link>
          <WebsiteLink />
        </div>
        <article className="rounded-3xl bg-white p-6 shadow-xs ring-1 ring-zinc-900/5 sm:p-10">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-600">BlackSync AI</p>
          <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight text-zinc-900">Terms of Service &amp; Subscription Agreement</h1>
          <p className="mt-3 text-sm text-zinc-500">
            Effective Date: {TERMS_EFFECTIVE} · Provider: BlackSync AI LLC · Version {TERMS_VERSION}
          </p>
          <p className="mt-6 text-[15px] leading-relaxed text-zinc-700">
            By creating a paid subscription or using BlackSync AI, you agree to the following terms.
          </p>
          <ol className="mt-8 space-y-8">
            {SECTIONS.map((s, i) => (
              <li key={s.title} id={s.title.toLowerCase().replace(/[^a-z]+/g, "-")}>
                <h2 className="font-display text-lg font-semibold text-zinc-900">
                  {i + 1}. {s.title}
                </h2>
                <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-zinc-700">
                  {s.body.map((b, j) =>
                    Array.isArray(b) ? (
                      <ul key={j} className="list-disc space-y-1.5 pl-5 marker:text-zinc-400">
                        {b.map((x) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    ) : (
                      <p key={j}>{b}</p>
                    ),
                  )}
                </div>
              </li>
            ))}
            <li id="contact">
              <h2 className="font-display text-lg font-semibold text-zinc-900">9. Contact</h2>
              <div className="mt-3 space-y-1 text-[15px] leading-relaxed text-zinc-700">
                <p>BlackSync AI LLC</p>
                <p>
                  Email:{" "}
                  <a href="mailto:support@blacksync.ai" className="font-medium text-brand-700 hover:underline">
                    support@blacksync.ai
                  </a>
                </p>
                <p>
                  Website:{" "}
                  <a href="https://blacksync.ai" className="font-medium text-brand-700 hover:underline">
                    https://blacksync.ai
                  </a>
                </p>
              </div>
            </li>
          </ol>
        </article>
      </div>
    </main>
  );
}
