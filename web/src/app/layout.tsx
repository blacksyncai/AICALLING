import type { Metadata } from "next";
import "@fontsource-variable/space-grotesk";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { ClerkProvider } from "@clerk/nextjs";
import { ToastProvider } from "@/components/toast";
import { clerkAppearance } from "@/lib/clerk";
import "./globals.css";
import { BrandingProvider } from "@/lib/branding";
import { hostBranding } from "@/lib/branding-server";
import { clerkDomainOptions } from "@/lib/white-label-clerk";
import { headers } from "next/headers";

export async function generateMetadata(): Promise<Metadata> {
  const brand = await hostBranding();
  return {
    title: { default: brand.name, template: `%s · ${brand.name}` },
    description: `Build, test and launch ${brand.name} AI voice agents that call your leads.`,
    ...(brand.logo_url ? { icons: { icon: brand.logo_url } } : {}),
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const brand = await hostBranding();
  const domainOptions = brand.custom ? clerkDomainOptions((await headers()).get("host") ?? "") : {};
  const content = <BrandingProvider brand={brand}><ToastProvider>{children}</ToastProvider></BrandingProvider>;
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen font-sans">
        {process.env.CLERK_SECRET_KEY ? <ClerkProvider appearance={clerkAppearance} {...domainOptions}
          signInUrl={domainOptions.signInUrl ?? "/sign-in"} signUpUrl={domainOptions.signUpUrl ?? "/sign-up"} afterSignOutUrl="/sign-in">
          {content}
        </ClerkProvider> : content}
      </body>
    </html>
  );
}
