import type { Metadata } from "next";
import "@fontsource-variable/space-grotesk";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { ClerkProvider } from "@clerk/nextjs";
import { ToastProvider } from "@/components/toast";
import { clerkAppearance } from "@/lib/clerk";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "BlackSync", template: "%s · BlackSync" },
  description: "Build, test and launch BlackSync AI voice agents that call your leads.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen font-sans">
        <ClerkProvider appearance={clerkAppearance} signInUrl="/sign-in" signUpUrl="/sign-up" afterSignOutUrl="/sign-in">
          <ToastProvider>{children}</ToastProvider>
        </ClerkProvider>
      </body>
    </html>
  );
}
