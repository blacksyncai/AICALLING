export interface PlanInfo {
  status: string;
  plan_key: string | null;
  name: string | null;
  managed?: boolean;
  amount_cents?: number | null;
  included_credits?: number | null;
  current_period_end?: string | null;
  cancel_at_period_end?: boolean;
}

export interface CreditBreakdown {
  balance: number;
  included: number;
  included_expires_at: string | null;
  purchased: number;
  other: number;
  cents_per_credit: number;
  unlimited: boolean;
}

export interface LookupStatus {
  balance_cents: number;
  prepaid_credits: number;
  unlimited: boolean;
  free_daily: number;
  free_used_today: number;
  free_remaining: number;
  price_cents: number | null;
  paid_enabled: boolean;
  policy: "match" | "completed";
  funds_options: { key: string; amount_cents: number }[];
}

export interface PhoneSummary {
  active: number;
  included: number;
  billable: number;
  billed_quantity: number;
  unit_cents: number;
  subscribed: boolean;
}

export interface Activity {
  type: "credits" | "lookup";
  id: string;
  amount?: number;
  amount_cents?: number;
  kind: string;
  note: string;
  created_at: string | null;
}

export interface Overview {
  plan: PlanInfo;
  credits: CreditBreakdown & { used_30d: number; minutes_30d: number; estimated_value_cents: number };
  lookups: LookupStatus;
  phones: PhoneSummary;
  auto_recharge: { enabled: boolean; threshold: number | null; pack_key: string | null; last_error: string | null };
  activity: Activity[];
  stripe_ready: boolean;
  can_manage: boolean;
}

export interface Pack {
  key: string;
  name: string;
  credits: number;
  amount_cents: number;
  blurb: string;
  suggested?: boolean;
  available: boolean;
  cents_per_credit: number;
}

export interface Plan {
  key: string;
  name: string;
  amount_cents: number;
  interval: string;
  included_credits: number;
  features: string[];
  tagline?: string;
  features_title?: string;
  available: boolean;
}

export interface Catalog {
  stripe_ready: boolean;
  plans: Plan[];
  packs: Pack[];
  lookup_funds: { key: string; name: string; amount_cents: number; available: boolean }[];
  phone_addon: { amount_cents: number; available: boolean };
  current_plan: PlanInfo;
}

export interface LedgerRow {
  id: string;
  amount: number;
  balance_after: number;
  kind: string;
  note: string;
  call_id: string | null;
  created_at: string | null;
}

export interface Card {
  id: string;
  brand: string | null;
  last4: string | null;
  exp_month: number | null;
  exp_year: number | null;
}

export interface AutoRechargeCfg {
  enabled: boolean;
  pack_key: string;
  threshold: number;
  monthly_limit_cents: number;
  month_to_date_cents: number;
  authorized_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  pending: boolean;
  card: Card | null;
  max_monthly_cents?: number;
}

export interface Purchase {
  id: string;
  kind: "credit_pack" | "lookup_funds" | "auto_recharge";
  pack_key: string | null;
  amount_cents: number;
  credits: number;
  status: string;
  error: string | null;
  refunded_cents: number;
  created_at: string | null;
  fulfilled_at: string | null;
}

export const usd = (cents: number | null | undefined, digits = 2) =>
  cents == null ? "—" : `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";

export const fmtDateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
