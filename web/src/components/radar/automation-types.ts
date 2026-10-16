export interface Condition {
  kind: "verification" | "outcome" | "field";
  value: string;
  field: string;
  operator: "equals" | "contains" | "exists";
}
export interface Action {
  kind:
    "blacksync_pond" | "crm_pond" | "crm_stage" | "crm_tag" | "crm_deal_stage";
  target_id: string;
  pipeline_id: string;
}
export interface Spec {
  source: {
    agent_id: string | null;
    campaign_id: string | null;
    blacksync_pond_id?: string | null;
    lead_source?: string;
    pond_id: string;
  };
  condition: Condition;
  actions: Action[];
}
export interface Rule {
  id?: string;
  name: string;
  provider: string;
  request: string;
  spec: Spec;
  status?: "draft" | "active" | "paused";
  version?: number;
  dirty?: boolean;
  requested_destination?: string;
}
export interface Choice {
  id: string;
  name: string;
  members?: number;
}
export interface Resources {
  provider: string;
  provider_name: string;
  assistant_tools?: { action: string; writes: boolean }[];
  blacksync_ponds: Choice[];
  crm_ponds: Choice[];
  pipelines: {
    id: string;
    name: string;
    stages: { id: string; label: string; kind?: string }[];
  }[];
  deal_pipelines: (Choice & {
    stages?: { id: string; label: string; kind?: string }[];
  })[];
  warnings: string[];
  capabilities: {
    create_blacksync_pond: boolean;
    route_pond: boolean;
    route_stage: boolean;
    tag: boolean;
    create_pond: boolean;
    create_stage: boolean;
    create_pipeline: boolean;
  };
}
export interface Overview {
  rules: Rule[];
  connections: { provider: string; name: string; label: string }[];
  agents: Choice[];
  campaigns: Choice[];
}
export interface Evidence {
  turn: number;
  role: string;
  text: string;
}
export interface PreviewItem {
  call_id: string;
  lead_id: string;
  name: string;
  phone: string;
  outcome: string;
  status: string;
  evidence: Evidence[];
  matches: boolean;
  reason: string;
}
export interface Preview {
  items: PreviewItem[];
  matched: number;
  checked: number;
  writes_performed: boolean;
  limit: number;
}
export const VERIFICATION_LABELS: Record<string, string> = {
  name_confirmed: "Name confirmed in conversation",
  named_voicemail: "Expected name in voicemail",
  wrong_number: "Wrong number",
  unverified: "Unverified",
};
export const OUTCOMES = [
  "meeting_booked",
  "qualified",
  "not_qualified",
  "interested",
  "not_interested",
  "callback",
  "transferred",
  "voicemail",
  "no_answer",
  "completed",
  "failed",
  "wrong_number",
  "do_not_call",
];
export const blankRule = (provider: string): Rule => ({
  name: "Verify and route contacts",
  provider,
  request: "",
  status: "draft",
  dirty: true,
  spec: {
    source: { agent_id: null, campaign_id: null, pond_id: "" },
    condition: {
      kind: "verification",
      value: "name_confirmed",
      field: "",
      operator: "equals",
    },
    actions: [],
  },
});
export function destinations(
  r: Resources,
): { label: string; action: Action }[] {
  return [
    ...r.blacksync_ponds.map((p) => ({
      label: `BlackSync pond · ${p.name}`,
      action: {
        kind: "blacksync_pond" as const,
        target_id: p.id,
        pipeline_id: "",
      },
    })),
    ...(r.capabilities.route_pond
      ? r.crm_ponds.map((p) => ({
          label: `${r.provider_name} pond · ${p.name}`,
          action: {
            kind: "crm_pond" as const,
            target_id: p.id,
            pipeline_id: "",
          },
        }))
      : []),
    ...(r.provider === "followupboss"
      ? r.deal_pipelines.flatMap((p) =>
          (p.stages || [])
            .filter((s) => s.kind !== "closed")
            .map((s) => ({
              label: `Deals · ${p.name} · ${s.label}`,
              action: {
                kind: "crm_deal_stage" as const,
                target_id: s.id,
                pipeline_id: p.id,
              },
            })),
        )
      : []),
    ...r.pipelines.flatMap((p) =>
      p.stages.map((s) => ({
        label: `${p.name} · ${s.label}`,
        action: {
          kind: "crm_stage" as const,
          target_id: s.id,
          pipeline_id: p.id,
        },
      })),
    ),
  ];
}
