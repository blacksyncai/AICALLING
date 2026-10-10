export type Funnel = { dialed: number; connected: number; conversations: number; qualified: number; booked: number };

export type AgentRow = { agent_id: string | null; name: string; calls: number; connected: number; booked: number; minutes: number; connect_rate: number; book_rate: number };
export type CampaignRow = { campaign_id: string; name: string; calls: number; connected: number; booked: number; book_rate: number };
export type HourRow = { hour: number; calls: number; connected: number };

export type Analytics = {
  days: number;
  funnel: Funnel;
  outcomes: Record<string, number>;
  by_agent: AgentRow[];
  by_campaign: CampaignRow[];
  by_hour: HourRow[];
  sentiment: { positive: number; neutral: number; negative: number };
  avg_talk_seconds: number;
  total_minutes: number;
  credits_used: number;
};

export const pct = (n: number, d: number) => (d ? Math.round((n / d) * 100) : 0);
