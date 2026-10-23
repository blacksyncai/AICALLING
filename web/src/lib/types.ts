import type { BuilderInfo } from "@/lib/builder";

export interface ExtractionField {
  name: string;
  description: string;
}

export interface Agent {
  id: string;
  template: string;
  name: string;
  description: string;
  status: "active" | "paused";
  system_prompt: string;
  first_message: string;
  knowledge_base: string;
  language: string;
  llm_model: string;
  temperature: number;
  voice_id: string;
  voice_speed: number;
  /** Empty object = defaults (volume 1, responsiveness 0.75, interruption 0.75). */
  voice_tuning?: VoiceTuning;
  background_audio: boolean;
  enable_booking: boolean;
  calcom_event_type_id: string;
  /** Write-only: set to save a new Cal.com key, "" to remove it. Never sent back by the API. */
  calcom_api_key?: string;
  calcom_key_set?: boolean;
  calendar_timezone?: string;
  voicemail_action?: "hang_up" | "leave_message" | "ignore";
  screener_action?: "answer" | "hang_up";
  pinned?: boolean;
  voicemail_message?: string;
  transfer_number: string;
  transfer_mode?: "cold" | "warm";
  transfer_handoff?: string;
  transfer_ring_seconds?: number;
  max_duration_seconds: number;
  extraction_fields: ExtractionField[];
  success_criteria: string;
  created_at: string;
  updated_at: string;
  stats?: { calls: number; seconds: number };
  builder?: BuilderInfo | null;
  ai_disclosure?: boolean;
  caller_number?: string;
  record_calls?: boolean;
  /** Short badge for what the agent does ("Expired Listings"); "" when unknown. */
  specialty?: string;
  /** True when a person set the specialty (regeneration leaves it alone). */
  specialty_custom?: boolean;
}

export interface VoiceTuning {
  voicemail_min_connected_seconds?: number;
  volume?: number;
  responsiveness?: number;
  interruption?: number;
  pronunciations?: { word: string; say: string }[];
}

export interface PhoneNumberItem {
  registration?: { status: string; providers: {provider: string; status: string; prerequisite: string; request_id: string | null}[] };
  /** Last 7 days of outbound calls from this number, and whether it's resting from campaign rotation. */
  health?: {
    dials_7d: number;
    pickups_7d: number;
    dials_24h: number;
    pickup_rate: number | null;
    avg_talk_seconds: number;
    low_pickups: boolean;
    resting_until: string | null;
    rest_reason: string;
  };
  carrier?: "twilio" | "bandwidth" | "signalwire";
  id: string;
  number: string;
  label: string;
  source: "purchased" | "imported" | "assigned";
  is_default: boolean;
  status: string;
  created_at: string | null;
}

export interface PhoneNumberRequestItem {
  id: string;
  area_code: string;
  note: string;
  status: "open" | "fulfilled" | "declined";
  created_at: string | null;
}

export interface MyPhoneNumbers {
  purchase_carriers?: string[];
  numbers: PhoneNumberItem[];
  requests: PhoneNumberRequestItem[];
  self_serve: boolean;
  recordings_enabled: boolean;
  pricing?: { active: number; included: number; included_on_plan: number; unit_cents: number; subscribed: boolean };
}

export interface AgentTemplate {
  template: string;
  name: string;
  description: string;
  enable_booking: boolean;
}

export interface Campaign {
  id: string;
  name: string;
  description: string;
  status: "draft" | "running" | "paused" | "completed" | "cancelled";
  /** Why the system paused it ("credits"); null when a person paused it. */
  pause_reason?: string | null;
  /** "outbound" dials a contact list; "inbound" answers calls to one of your numbers. */
  direction?: "outbound" | "inbound";
  phone_number_id?: string | null;
  agent_id: string | null;
  max_concurrent_calls: number;
  // Calling hours (local time in `timezone`) and automatic retries.
  call_window_start: string;
  call_window_end: string;
  call_days: number[];
  timezone: string;
  max_attempts: number;
  retry_delay_minutes: number;
  /** Minutes to wait before each retry, in order ([] = call once). */
  retry_schedule: number[];
  number_rotation_enabled?: boolean;
  caller_number_pool?: string[];
  /** Warm-up pacing: slow dialing with rest pauses (null = off). */
  warmup_enabled?: boolean | null;
  warmup_min_gap_seconds?: number | null;
  warmup_max_gap_seconds?: number | null;
  warmup_batch_size?: number | null;
  warmup_rest_seconds?: number | null;
  retry_caller_policy?: "same" | "different";
  max_calls_per_number_day?: number;
  within_calling_hours: boolean;
  next_window_at: string | null;
  pending_retries: number;
  total_targets: number;
  total_dialed: number;
  total_qualified: number;
  total_booked: number;
  created_at: string;
  updated_at: string;
}

export interface Lead {
  id: string;
  name: string;
  company: string;
  phone: string;
  email: string;
  role: string;
  status: string;
  notes: string | null;
  custom_fields: Record<string, string>;
  created_at: string;
}

export interface TranscriptTurn {
  role: "assistant" | "user" | "tool";
  text?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: { output?: unknown };
  ts?: number;
}

export interface Call {
  id: string;
  call_type: "outbound" | "web" | "inbound";
  status: string;
  outcome: string | null;
  sentiment: string | null;
  summary: string | null;
  duration_seconds: number | null;
  to_phone: string | null;
  contact_name: string | null;
  contact_company: string | null;
  agent_id: string | null;
  agent_name: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  meeting_link: string | null;
  agreed_meeting_time: string | null;
  started_at: string;
  ended_at: string | null;
  transcript?: TranscriptTurn[];
  extracted_data?: Record<string, unknown>;
  metrics?: { turns: number; avg_response: number | null; avg_eou: number | null; avg_llm_ttft: number | null; avg_tts_ttfb: number | null; response_metric?: string; response_gap_samples?: number; p50_turn_gap?: number; p95_turn_gap?: number; max_turn_gap?: number; avg_interruption_recovery?: number } | null;
  from_phone?: string | null;
  has_recording?: boolean;
  prospect_email?: string | null;
  credits_charged?: number | null;
  /** Exact credits this call used (per second at its rate); 0 when it never connected. */
  credits_used?: number | null;
  /** How credits_used adds up (null when the call wasn't billed). */
  credit_breakdown?: { rate: number; ai: number; phone_fee: number; free_seconds: number; billed_seconds: number } | null;
  lead_id?: string | null;
}

export interface OverviewTotals {
  total_calls: number;
  connected_calls: number;
  total_minutes: number;
  avg_duration_seconds: number;
  meetings_booked: number;
  success_rate: number;
  connect_rate: number;
  meaningful_calls: number;
  follow_ups: number;
}

export interface Overview extends OverviewTotals {
  previous: OverviewTotals;
  outcomes: Record<string, number>;
  calls_per_day: { date: string; calls: number; connected: number; booked: number }[];
  agents: number;
  running_campaigns: number;
  days: number;
  total_leads: number;
  new_leads: number;
  previous_new_leads: number;
  credits_balance: number;
  unlimited_credits: boolean;
}

export interface SettingsStatus {
  database: string;
  integrations: Record<"openai" | "livekit" | "deepgram" | "cartesia" | "sip_trunk" | "calcom", boolean>;
  capabilities: Record<"chat_test" | "web_call" | "phone_call" | "post_call_analysis", boolean>;
  livekit_url: string;
  agent_name: string;
}

export interface Voice {
  id: string;
  name: string;
  provider?: "cartesia" | string;
  /** "premium" = house voices + the account's own/cloned voices; everything else "standard". */
  category?: "premium" | "standard";
  gender?: string | null;
  language?: string | null;
  accent?: string | null;
  description?: string;
  /** True only for voices owned by (cloned in) the account. */
  is_clone?: boolean;
  /** Previews can be generated (a Cartesia key is set). */
  preview?: boolean;
  models?: string[];
  status?: string;
  /** Legacy alias of is_clone. */
  mine?: boolean;
  /** One speaker offered in several tones: the picker shows one row per family with tone chips. */
  family?: string | null;
  tone?: string | null;
}

export interface VoiceCategory {
  key: "premium" | "standard";
  label: string;
  count: number;
}

export interface VoiceCatalog {
  source: "cartesia" | "fallback" | string;
  voices: Voice[];
  featured?: Voice[];
  categories?: VoiceCategory[];
  preview_available?: boolean;
  message?: string | null;
}

export interface ModelOption {
  id: string;
  name: string;
  provider: string;
  description: string;
  speed?: "fast" | "standard" | null;
  tags: ("recommended" | "fast" | "advanced")[];
  /** Agent traits this model suits: general · booking · transfer · complex_scripts. */
  recommended_for: string[];
  status: string;
  group: "recommended" | "fast" | "advanced" | "other";
}

export interface ModelCatalog {
  models: ModelOption[];
  groups: { key: ModelOption["group"]; label: string; models: string[] }[];
  default: string;
  languages: { code: string; label: string; stt: boolean; tts: boolean }[];
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ToolEvent {
  tool: string;
  args: Record<string, unknown>;
  result: string;
}

// ── Accounts ──────────────────────────────────────────────────────────────────

export type Role = "owner" | "admin" | "member";

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  is_superadmin: boolean;
  created_at: string | null;
}

export interface Org {
  id: string;
  name: string;
  status: "active" | "suspended";
  credits_balance: number;
  unlimited_credits: boolean;
  /** IANA time zone used for reports (days on the dashboard, the call-log day filter). */
  timezone?: string | null;
  lead_finder_enabled?: boolean;
  /** Industry chosen at free-trial onboarding (agent catalog key). */
  industry?: string | null;
  onboarding?: { goals?: string[]; other_goal?: string; team_size?: string | null; trial_credits?: number } | null;
  /** Lead-lookup credits (separate from calling credits). */
  lead_credits?: number;
  lead_credits_unlimited?: boolean;
  created_at: string | null;
}

export interface Session {
  user: User;
  org: Org | null;
  /** "superadmin" when a platform admin is viewing an account they aren't a member of. */
  role: Role | "superadmin";
  impersonating: boolean;
  memberships: { org_id: string; org_name: string; role: Role }[];
  auth_provider: "clerk" | "password";
}

export interface Member extends User {
  membership_id: string;
  role: Role;
  last_login_at: string | null;
  joined_at: string | null;
}

export interface PendingInvite {
  id: string;
  email: string;
  role: Role;
  expires_at: string | null;
  created_at: string | null;
}

/** Returned once when an invite is created. */
export interface CreatedInvite extends PendingInvite {
  invite_url: string;
  emailed: boolean;
}

export interface Team {
  members: Member[];
  invites: PendingInvite[];
  email_enabled: boolean;
}

/** GET /api/account/org */
export interface OrgDetail extends Org, Team {
  role: Role | "superadmin";
  can_manage: boolean;
}

export interface CreditTransaction {
  id: string;
  amount: number;
  balance_after: number;
  kind: "grant" | "usage" | "adjustment";
  note: string;
  call_id: string | null;
  created_at: string | null;
}

/** GET /api/account/credits */
export interface CreditHistory {
  balance: number;
  unlimited: boolean;
  transactions: CreditTransaction[];
}

// ── Contacts (CRM) ────────────────────────────────────────────────────────────

export interface Contact {
  id: string;
  name: string;
  company: string;
  phone: string;
  email: string;
  role: string;
  status: string;
  notes: string;
  tags: string[];
  custom_fields: Record<string, string>;
  source: string;
  campaign_id: string | null;
  campaign_name: string | null;
  last_called_at: string | null;
  do_not_call: boolean;
  attempts: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ContactCall {
  id: string;
  status: string;
  outcome: string | null;
  summary: string | null;
  duration_seconds: number | null;
  agent_name: string | null;
  started_at: string | null;
}

export interface ContactDetail extends Contact {
  calls: ContactCall[];
}

/** GET /api/contacts */
export interface ContactList {
  items: Contact[];
  total: number;
  page: number;
  page_size: number;
  status_counts: Record<string, number>;
}

// ── Integrations ──────────────────────────────────────────────────────────────

export type WebhookEvent = "call.completed" | "meeting.booked" | "contact.created";

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string | null;
  last_used_at: string | null;
}

export interface Webhook {
  id: string;
  name: string;
  url: string;
  events: WebhookEvent[];
  secret: string;
  active: boolean;
  last_status: number | null;
  last_error: string | null;
  last_sent_at: string | null;
  created_at: string | null;
}

/** GET /api/integrations */
export interface Integrations {
  api_keys: ApiKey[];
  webhooks: Webhook[];
  events: WebhookEvent[];
}

// ── Admin portal ──────────────────────────────────────────────────────────────

export interface Usage {
  calls: number;
  minutes: number;
  credits_used: number;
}

export interface AdminOrg extends Org {
  owner: { name: string; email: string } | null;
  members: number;
  agents: number;
  contacts: number;
  usage_30d: Usage;
  all_time?: Usage;
  phone_numbers?: number;
  lookup_balance_cents?: number;
}

export interface AdminOrgDetail extends Org, Team {
  usage_30d: Usage;
  all_time: { calls: number; minutes: number };
  agents: number;
  campaigns: number;
  contacts: number;
  transactions: CreditTransaction[];
}

export interface PlatformOverview {
  accounts: number;
  users: number;
  calls_30d: number;
  minutes_30d: number;
  credits_used_30d: number;
  credits_outstanding: number;
}

/** POST /api/admin/orgs */
export interface CreatedOrg extends Org {
  login_email: string;
  owner_status: "created" | "invited" | "existing_user_added";
  temporary_password?: string | null;
  invite_url?: string;
  emailed?: boolean;
}

// ── Dashboard activity heat map (GET /api/activity/daily) ─────────────────────

export type ActivityMetric = "calls" | "connected" | "appointments" | "transfers" | "credits";
export type ActivityRange = "30d" | "90d" | "12m";

export interface ActivityDay {
  date: string;
  /** The selected metric for this day. */
  value: number;
  calls: number;
  connected: number;
  appointments: number;
  transfers: number;
  credits: number;
  /** Top agents for the selected metric that day (agent id is null for a removed agent). */
  agents: { id: string | null; name: string; value: number }[];
}

export interface ActivityResponse {
  metric: ActivityMetric;
  range: ActivityRange;
  timezone: string;
  start: string;
  end: string;
  agent: { id: string; name: string } | null;
  /** Only days with any activity. */
  days: ActivityDay[];
  totals: Record<ActivityMetric | "value" | "active_days", number>;
  metric_available: boolean;
  /** False for unlimited-calling accounts, where no credits are deducted. */
  credits_tracked: boolean;
  note: string | null;
}
