export interface LeadFinderUsage {
  enabled: boolean;
  /** False until the DataSkip key is set on the backend. */
  configured: boolean;
  used: number;
  limit: number;
  remaining: number;
  /** Next allowance reset (UTC midnight), ISO. */
  resets_at: string;
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
  /** Listed on a Do Not Call registry, per DataSkip. */
  dnc: boolean;
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
