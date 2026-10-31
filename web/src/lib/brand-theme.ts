export type BrandKit = { primary: string; accent: string; sidebar: string; surface: string; text: string;
  font: "geist" | "grotesk" | "system"; button_shape: "rounded" | "pill" | "square" };
export const DEFAULT_KIT: BrandKit = { primary: "#dc4a1e", accent: "#f59e0b", sidebar: "#181411",
  surface: "#f8f6f3", text: "#211b18", font: "geist", button_shape: "rounded" };

export function mix(color: string, target: number, amount: number) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) color = DEFAULT_KIT.primary;
  const rgb = [1, 3, 5].map(i => Math.round(parseInt(color.slice(i, i + 2), 16) * (1 - amount) + target * amount));
  return `#${rgb.map(v => v.toString(16).padStart(2, "0")).join("")}`;
}

export function primaryText(color: string) {
  const rgb = [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16) / 255);
  const linear = rgb.map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  const l = linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
  return (l + .05) / .05 > 1.05 / (l + .05) ? "#000000" : "#ffffff";
}

export function brandVariables(kit: BrandKit): Record<string, string> {
  const vars: Record<string, string> = {
    "--brand-primary": kit.primary, "--brand-accent": kit.accent, "--brand-on-primary": primaryText(kit.primary),
    "--app-surface": kit.surface, "--app-text": kit.text, "--sidebar-surface": kit.sidebar,
    "--brand-radius": { rounded: ".5rem", pill: "999px", square: ".15rem" }[kit.button_shape],
    "--brand-glow": `${kit.primary}66`,
  };
  for (const [shade, blend] of [[50, .94], [100, .86], [200, .7], [300, .5], [400, .25]])
    vars[`--color-brand-${shade}`] = mix(kit.primary, 255, blend);
  vars["--color-brand-500"] = vars["--color-brand-600"] = kit.primary;
  vars["--color-brand-700"] = mix(kit.primary, 0, .2);
  vars["--color-brand-800"] = mix(kit.primary, 0, .4);
  const font = { geist: 'var(--font-geist-sans), sans-serif', grotesk: '"Space Grotesk Variable", sans-serif',
    system: 'system-ui, sans-serif' }[kit.font];
  vars["--font-sans"] = vars["--font-display"] = font;
  return vars;
}
