import { api, post } from "@/lib/api";
import type { BusinessProfile, KnowledgeSection } from "@/lib/builder";

export const PROFILE_URL = "/api/business-profile";
export const REVISIONS_URL = "/api/business-profile/revisions";

export type Revision = { id: string; summary: string; created_at: string };

const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const profileApi = {
  update: (body: Partial<Pick<BusinessProfile, "name" | "industry" | "website" | "description" | "auto_refresh_days">>) =>
    put<BusinessProfile>(PROFILE_URL, body),
  analyze: (website?: string) => post<BusinessProfile>(`${PROFILE_URL}/analyze`, website ? { website } : {}),
  rescan: () => post<BusinessProfile>(`${PROFILE_URL}/rescan`),
  saveKnowledge: (sections: KnowledgeSection[]) => put<BusinessProfile>(`${PROFILE_URL}/knowledge`, { sections }),
  upload: (filename: string, text: string) => post<BusinessProfile>(`${PROFILE_URL}/knowledge/upload`, { filename, text }),
  applyChanges: (ids: string[]) => post<BusinessProfile>(`${PROFILE_URL}/changes/apply`, { ids }),
  dismissChanges: (ids: string[]) => post<BusinessProfile>(`${PROFILE_URL}/changes/dismiss`, { ids }),
  restore: (id: string) => post<BusinessProfile>(`${PROFILE_URL}/revisions/${encodeURIComponent(id)}/restore`),
};

export const SCAN_STEPS = [
  "Exploring your website",
  "Understanding your business",
  "Identifying services and team details",
  "Preparing your knowledge base",
];

export function newItemId(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return `k_${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

export function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname === "/" ? "" : u.pathname.replace(/\/$/, "");
    return `${u.hostname.replace(/^www\./, "")}${path}`;
  } catch {
    return url;
  }
}

/** Read a small text file in the browser (FileReader) — .txt/.md/.csv only. */
export function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(new Error(`Couldn't read ${file.name}`));
    r.readAsText(file);
  });
}
