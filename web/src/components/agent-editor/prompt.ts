import { PROMPT_SECTIONS } from "@/lib/builder";

export type SectionKey = (typeof PROMPT_SECTIONS)[number][0];

export const SECTION_LABEL: Record<string, string> = Object.fromEntries(PROMPT_SECTIONS);

/**
 * Rebuild the full system prompt from builder sections, the same way the backend does:
 * `## {Heading}\n\n{text}` for each section (PROMPT_SECTIONS order), joined by blank lines.
 * Empty sections are left out.
 */
export function assemblePrompt(sections: Record<string, string>): string {
  return PROMPT_SECTIONS.map(([key, label]) => [label, (sections[key] ?? "").trim()] as const)
    .filter(([, text]) => text)
    .map(([label, text]) => `## ${label}\n\n${text}`)
    .join("\n\n");
}

export function humanizeKey(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
