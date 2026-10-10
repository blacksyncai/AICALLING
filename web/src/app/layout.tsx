import type { Metadata } from "next";
import "@fontsource-variable/space-grotesk";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { ToastProvider } from "@/components/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "BlackSync", template: "%s · BlackSync" },
  description: "Build, test and launch BlackSync AI voice agents that call your leads.",
  icons: { icon: "/favicon.svg", apple: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen font-sans">
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
