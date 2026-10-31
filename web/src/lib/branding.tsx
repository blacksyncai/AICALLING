"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";

export type Brand = { name: string; logo_url: string | null; custom: boolean };
export const DEFAULT_BRAND: Brand = { name: "BlackSync", logo_url: null, custom: false };
const Branding = createContext<Brand>(DEFAULT_BRAND);

export function BrandingProvider({ brand, children }: { brand?: Brand; children: ReactNode }) {
  const inherited = useContext(Branding);
  const pathname = usePathname();
  const current = pathname?.startsWith("/admin") ? DEFAULT_BRAND : brand ?? inherited;
  useEffect(() => {
    if (current.custom) document.title = document.title.replace(/BlackSync/g, () => current.name);
  }, [current.name, current.custom, pathname]);
  return <Branding.Provider value={current}>{children}</Branding.Provider>;
}

export const useBranding = () => useContext(Branding);

export function BrandName() {
  return <>{useBranding().name}</>;
}

export function BrandedText({ text }: { text: string }) {
  const brand = useBranding();
  return <>{text.replace(/BlackSync/g, () => brand.name)}</>;
}
