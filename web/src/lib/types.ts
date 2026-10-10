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
  background_audio: boolean;
  enable_booking: boolean;
  calcom_event_type_id: string;
  transfer_number: string;
  max_duration_seconds: number;
  extraction_fields: ExtractionField[];
  success_criteria: string;
  created_at: string;
  updated_at: string;
  stats?: { calls: number; seconds: number };
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
  agent_id: string | null;
  max_concurrent_calls: number;
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
  call_type: "outbound" | "web";
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
  prospect_email?: string | null;
}

export interface Overview {
  total_calls: number;
  connected_calls: number;
  total_minutes: number;
  avg_duration_seconds: number;
  meetings_booked: number;
  success_rate: number;
  outcomes: Record<string, number>;
  calls_per_day: { date: string; calls: number }[];
  agents: number;
  running_campaigns: number;
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
  gender?: string;
  language?: string;
  description?: string;
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
