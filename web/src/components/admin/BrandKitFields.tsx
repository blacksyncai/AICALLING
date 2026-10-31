"use client";

import type { BrandKit } from "@/lib/brand-theme";
import { DEFAULT_KIT } from "@/lib/brand-theme";
import { Input } from "@/components/ui";

const PRESETS = [
  { name: "Copper", primary: "#dc4a1e", accent: "#f59e0b", sidebar: "#181411" },
  { name: "Ocean", primary: "#2458a6", accent: "#06a6b5", sidebar: "#10283e" },
  { name: "Forest", primary: "#176b4b", accent: "#b48a2b", sidebar: "#112e24" },
  { name: "Violet", primary: "#7545ad", accent: "#d96694", sidebar: "#261c39" },
];

export function BrandKitFields({ value, onChange, disabled }: { value: BrandKit; onChange: (kit: BrandKit) => void; disabled?: boolean }) {
  const set = <K extends keyof BrandKit>(key: K, v: BrandKit[K]) => onChange({ ...value, [key]: v });
  return <fieldset disabled={disabled} className="min-w-0 space-y-4 rounded-xl border border-zinc-200 p-4 disabled:opacity-50">
    <legend className="px-1 text-sm font-semibold">Brand scheme</legend>
    <div className="flex flex-wrap gap-2">{PRESETS.map(p => <button key={p.name} type="button"
      onClick={() => onChange({ ...DEFAULT_KIT, primary: p.primary, accent: p.accent, sidebar: p.sidebar })} className="flex items-center gap-2 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs hover:bg-zinc-50">
      <span className="h-3 w-3 rounded-full" style={{ background: p.primary }} />{p.name}</button>)}</div>
    <div className="grid gap-3 sm:grid-cols-2">{([
      ["primary", "Primary color"], ["accent", "Accent color"], ["sidebar", "Sidebar background (dark)"],
      ["surface", "Workspace background (light)"], ["text", "Workspace text"],
    ] as const).map(([key, label]) => <label key={key} className="space-y-1 text-xs font-medium text-zinc-600">
      <span>{label}</span><div className="flex gap-2"><input type="color" aria-label={`${label} picker`} value={/^#[0-9a-f]{6}$/i.test(value[key]) ? value[key] : DEFAULT_KIT[key]}
        onChange={e => set(key, e.target.value)} className="h-9 w-10 shrink-0 cursor-pointer rounded border border-zinc-200 bg-white p-1" />
        <Input className="min-w-0" value={value[key]} pattern="#[0-9a-fA-F]{6}" required maxLength={7} aria-label={label} onChange={e => set(key, e.target.value)} /></div>
    </label>)}</div>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1 text-xs font-medium text-zinc-600"><span>Typography</span><select aria-label="Typography" value={value.font} onChange={e => set("font", e.target.value as BrandKit["font"])} className="block h-9 w-full rounded-lg border border-zinc-200 bg-white px-2 text-sm">
        <option value="geist">Geist</option><option value="grotesk">Space Grotesk</option><option value="system">System font</option></select></label>
      <label className="space-y-1 text-xs font-medium text-zinc-600"><span>Button shape</span><select aria-label="Button shape" value={value.button_shape} onChange={e => set("button_shape", e.target.value as BrandKit["button_shape"])} className="block h-9 w-full rounded-lg border border-zinc-200 bg-white px-2 text-sm">
        <option value="rounded">Rounded</option><option value="pill">Pill</option><option value="square">Square</option></select></label>
    </div>
    <p className="text-xs text-zinc-400">Fonts are bundled with the app. Text/background and sidebar contrast are checked when you save.</p>
  </fieldset>;
}
