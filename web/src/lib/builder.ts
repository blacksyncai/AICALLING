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
  direction: "outbound" | "inbound" | "both";
  description: string;
  objectives: string[];
  qualification_questions: string[];
  actions: string[];
  followups: Followup[];
}

export interface BuilderCatalog {
  industries: { key: string; label: string; icon: string }[];
  use_cases: Record<string, UseCase[]>;
  /** Alternate keys accepted in drafts and saved agents. */
  use_case_aliases?: Record<string, string>;
  styles: { key: string; label: string; description: string }[];
  integrations: {
    key: string;
    label: string;
    category: string;
    status: "available" | "needs_setup" | "coming_soon";
    detail: string;
    /** Industries where this tool is popular (shown first). */
    industries?: string[];
  }[];
}

/** Key of the "Create your own" option in every industry's use cases. */
export const CUSTOM_USE_CASE = "custom";

/** One follow-up from the AI assistant and the user's reply. */
export interface AssistItem {
  id: string;
  question: string;
  /** null while unanswered; "You decide" when the user let the AI choose. */
  answer: string | null;
  skipped: boolean;
  delegated?: boolean;
  suggestions?: string[];
  reason?: string;
}

export interface AssistQuestion {
  id: string;
  question: string;
  suggestions: string[];
  reason?: string;
}

/** POST /api/agent-builder/assist */
export interface AssistResponse {
  understanding: string;
  questions: AssistQuestion[];
  ready: boolean;
  recommendation: string | null;
  /** Previously answered question ids that no longer apply to the goal. */
  irrelevant: string[];
  rounds_left: number;
}

export interface CustomGoal {
  description?: string;
  audience?: string;
  tone?: string;
  outcome?: string;
}

export interface DraftGoal {
  direction?: "outbound" | "inbound" | "both";
  /** Primary use case (first of use_cases) — kept for older drafts and agents. */
  use_case?: string;
  /** Selected presets in order; may include "custom" (Create your own). */
  use_cases?: string[];
  /** Older drafts: answers to per-use-case followups. */
  answers?: Record<string, string | boolean>;
  custom?: CustomGoal;
  extra_instructions?: string;
  assistant?: AssistItem[];
  understanding?: string;
  recommendation?: string | null;
  ready?: boolean;
  /** Completed assist rounds for the current goal (capped server-side). */
  assist_rounds?: number;
  /** Fingerprint of the goal the assistant last reviewed. */
  assist_basis?: string;
}

export interface DraftData {
  /** 2 = Business · Goal · Fine-tune · Review. Older drafts (no v) used six steps. */
  v?: number;
  business?: { name?: string; industry?: string; website?: string; description?: string };
  goal?: DraftGoal;
  behavior?: {
    /** "I'll decide later": recommended defaults for everything below. */
    decide_later?: boolean;
    agent_name?: string;
    voice_id?: string;
    language?: string;
    style?: string;
    custom_style?: string;
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

// Keys and headings must match SECTION_TITLES in backend/app/agent/generator.py —
// the system prompt is assembled as "## {heading}" blocks in this order.
export const PROMPT_SECTIONS = [
  ["identity", "Identity and Style"],
  ["reason", "Purpose of the Call"],
  ["flow", "Conversation Flow"],
  ["qualification", "Qualification"],
  ["objections", "Handling Objections"],
  ["knowledge", "Using Business Knowledge"],
  ["booking", "Booking"],
  ["transfer", "Transferring to a Person"],
  ["voicemail", "Voicemail"],
  ["callback", "Callbacks"],
  ["closing", "Closing the Call"],
  ["compliance", "Honesty and Compliance"],
] as const;

export interface BuilderPlan {
  title?: string;
  primary_objective?: string;
  target_audience?: string;
  qualification_questions?: string[];
  desired_outcomes?: string[];
  transfer_rules?: string;
  booking_rules?: string;
  follow_up_logic?: string;
  use_cases?: string[];
  recommended_settings?: boolean;
}

export interface BuilderInfo {
  industry?: string;
  use_case?: string;
  use_cases?: string[];
  plan?: BuilderPlan;
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
