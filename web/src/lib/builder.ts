// Types for the agent builder (see docs/agent-builder.md).

export type KnowledgeOrigin = "website" | "manual" | "upload";

export interface KnowledgeItem {
  id: string;
  text: string;
  source_url: string | null;
  origin: KnowledgeOrigin;
  needs_review: boolean;
}

export interface KnowledgeSection {
  key: "overview" | "services" | "locations" | "team" | "hours" | "pricing" | "faqs" | "custom" | string;
  title: string;
  items: KnowledgeItem[];
}

export interface KnowledgeChange {
  id: string;
  section: string;
  action: "add" | "remove";
  item: KnowledgeItem;
}

export interface BusinessProfile {
  exists: boolean;
  name: string;
  industry: string;
  website: string;
  description: string;
  status: "idle" | "analyzing" | "ready" | "limited" | "failed";
  progress_step: number | null;
  progress_label: string | null;
  error: string | null;
  pages: { url: string; title: string }[];
  knowledge: { sections: KnowledgeSection[] };
  pending_changes: KnowledgeChange[];
  auto_refresh_days: number | null;
  scanned_at: string | null;
  item_count: number;
  review_count: number;
}

export interface Followup {
  key: string;
  label: string;
  type: "boolean" | "choice" | "text";
  options?: string[];
  default?: string | boolean;
}

export interface UseCase {
  key: string;
  label: string;
  direction: "outbound" | "inbound";
  description: string;
  objectives: string[];
  qualification_questions: string[];
  actions: string[];
  followups: Followup[];
}

export interface BuilderCatalog {
  industries: { key: string; label: string; icon: string }[];
  use_cases: Record<string, UseCase[]>;
  styles: { key: string; label: string; description: string }[];
  integrations: {
    key: string;
    label: string;
    category: string;
    status: "available" | "needs_setup" | "coming_soon";
    detail: string;
  }[];
}

export interface DraftData {
  business?: { name?: string; industry?: string; website?: string; description?: string };
  goal?: { direction?: "outbound" | "inbound" | "both"; use_case?: string; answers?: Record<string, string | boolean> };
  behavior?: {
    agent_name?: string;
    voice_id?: string;
    language?: string;
    style?: string;
    qualification_depth?: "light" | "standard" | "thorough";
    booking?: boolean;
    transfer_number?: string;
    transfer_when?: string;
    callback?: boolean;
    ai_disclosure?: boolean;
  };
  integrations?: { selected?: string[] };
}

export interface AgentDraft {
  id: string;
  step: number;
  data: DraftData;
  updated_at: string | null;
  agent_id: string | null;
}

export const PROMPT_SECTIONS = [
  ["identity", "Identity & introduction"],
  ["reason", "Reason for calling"],
  ["flow", "Conversation flow"],
  ["qualification", "Qualification"],
  ["objections", "Objection handling"],
  ["knowledge", "Using business knowledge"],
  ["booking", "Appointment scheduling"],
  ["transfer", "Warm transfers"],
  ["voicemail", "Voicemail"],
  ["callback", "Callbacks & follow-up"],
  ["closing", "Wrapping up"],
  ["compliance", "Disclosure & compliance"],
] as const;

export interface BuilderInfo {
  industry?: string;
  use_case?: string;
  direction?: string;
  style?: string;
  draft_id?: string;
  sections?: Record<string, string>;
}

export interface ReadinessCheck {
  key: string;
  label: string;
  status: "ok" | "warning" | "blocker";
  detail: string;
  fix_href?: string;
}
