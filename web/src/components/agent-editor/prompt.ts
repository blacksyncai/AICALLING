/** (key, heading) pairs in prompt order — see `sectionOrder()` in lib/builder. */
export type SectionOrder = readonly (readonly [string, string])[];

/**
 * Rebuild the full system prompt from builder sections, the same way the backend does:
 * `## {Heading}\n\n{text}` for each section (in the agent's section order), joined by blank lines.
 * Empty sections are left out.
 */
export function assemblePrompt(sections: Record<string, string>, order: SectionOrder): string {
  return order
    .map(([key, label]) => [label, (sections[key] ?? "").trim()] as const)
    .filter(([, text]) => text)
    .map(([label, text]) => `## ${label}\n\n${text}`)
    .join("\n\n");
}

export function countWords(s: string): number {
  return s.trim() ? s.trim().split(/\s+/).length : 0;
}

export function humanizeKey(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
