"use client";

import { createContext, useContext, useEffect, type CSSProperties, type ReactNode } from "react";
import { brandVariables, DEFAULT_KIT, type BrandKit } from "./brand-theme";
import { usePathname } from "next/navigation";

export type Brand = { name: string; logo_url: string | null; custom: boolean; kit?: BrandKit };
export const DEFAULT_BRAND: Brand = { name: "BlackSync", logo_url: null, custom: false };
const Branding = createContext<Brand>(DEFAULT_BRAND);

export function BrandingProvider({ brand, children }: { brand?: Brand; children: ReactNode }) {
  const inherited = useContext(Branding);
  const pathname = usePathname();
  const current = pathname?.startsWith("/admin") ? DEFAULT_BRAND : brand ?? inherited;
  useEffect(() => {
    if (current.custom) document.title = document.title.replace(/BlackSync/g, () => current.name);
  }, [current.name, current.custom, pathname]);
  return <Branding.Provider value={current}><div className="brand-scope" data-custom-brand={current.custom}
    style={current.custom ? brandVariables({ ...DEFAULT_KIT, ...current.kit }) as CSSProperties : undefined}>{children}</div></Branding.Provider>;
}

export const useBranding = () => useContext(Branding);

export function BrandName() {
  return <>{useBranding().name}</>;
}

export function BrandedText({ text }: { text: string }) {
  const brand = useBranding();
  return <>{text.replace(/BlackSync/g, () => brand.name)}</>;
}
