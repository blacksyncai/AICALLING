export interface LeadFinderUsage {
  enabled: boolean;
  /** False until the DataSkip key is set on the backend. */
  configured: boolean;
  /** Lead-lookup credits (separate from calling credits). 1 credit = 1 owner found. */
  credits: number;
  unlimited: boolean;
  retention_days: number;
}

export interface LookupAddress {
  street: string;
  city: string;
  state: string;
  zip: string;
}

export interface LookupPhone {
  number: string;
  display: string;
  type: "mobile" | "landline" | "unknown";
  /** DataSkip's DNC flag exactly as reported: true / false, or null when not reported. */
  dnc: boolean | null;
}

export interface PlaceAddress {
  address: string;
  city: string;
  state: string;
  zip: string;
}

export interface LookupResult {
  contact: {
    first_name: string;
    last_name: string;
    full_name: string;
    property: PlaceAddress;
    mailing: PlaceAddress;
  };
  phones: LookupPhone[];
  emails: string[];
}

export interface Lookup {
  id: string;
  address: LookupAddress;
  status: string;
  found: boolean | null;
  owner_name: string | null;
  lead_id: string | null;
  deleted: boolean;
  created_at: string | null;
  batch_id?: string | null;
  row?: number | null;
  phones?: number;
  error?: string | null;
  result?: LookupResult | null;
}

export interface LookupResponse {
  lookup: Lookup;
  cached: boolean;
  usage: LeadFinderUsage;
}

export interface ParsedAddress extends LookupAddress {
  confident: boolean;
}

export interface LookupBatch {
  id: string;
  filename: string;
  status: "draft" | "running" | "done" | "failed";
  total_rows: number;
  valid: number;
  invalid: { row: number; reason: string }[];
  processed: number;
  matched: number;
  no_match: number;
  failed: number;
  cached: number;
  credits_used: number;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

/** POST /api/lead-finder/batches — the parsed draft and what it will cost. */
export interface BatchPreview extends LookupBatch {
  cached_rows: number;
  new_rows: number;
  max_credits: number;
  enough_credits: boolean;
  usage: LeadFinderUsage;
}

export interface BatchDetail extends LookupBatch {
  rows: Lookup[];
  usage: LeadFinderUsage;
}
