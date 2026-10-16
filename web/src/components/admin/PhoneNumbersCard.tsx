"use client";

import { Phone, Search, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import useSWR, { mutate as refreshSWR } from "swr";
import { Badge, Button, Card, CardHeader, Field, Input, Notice, Spinner, Tabs } from "@/components/ui";
import { useToast } from "@/components/toast";
import { api, del, fetcher, post } from "@/lib/api";
import type { PhoneNumberItem, PhoneNumberRequestItem } from "@/lib/types";

interface OrgNumbers {
  numbers: PhoneNumberItem[];
  requests: PhoneNumberRequestItem[];
  twilio_ready: boolean;
}

interface Available {
  number: string;
  friendly: string;
  locality: string;
  region: string;
}

interface Owned {
  carrier?: string;
  sid: string;
  number: string;
  friendly: string;
  on_trunk: boolean;
  org_id: string | null;
  org_name: string | null;
}

type Mode = "buy" | "import";

/** Admin: one account's numbers — buy from Twilio, assign one already owned, or release. */
export function PhoneNumbersCard({ orgId }: { orgId: string }) {
  const toast = useToast();
  const url = `/api/admin/orgs/${orgId}/phone-numbers`;
  const { data, mutate } = useSWR<OrgNumbers>(url, fetcher);
  const [mode, setMode] = useState<Mode>("import");
  const [area, setArea] = useState("");
  const [results, setResults] = useState<Available[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { data: telephony } = useSWR<{ owned: Owned[]; owned_error: string; owned_warnings?: string[] }>(mode === "import" ? "/api/admin/telephony" : null, fetcher);

  const openRequest = data?.requests[0];

  async function search(e: FormEvent) {
    e.preventDefault();
    setSearching(true);
    try {
      const r = await api<{ numbers: Available[] }>(`/api/admin/phone-numbers/available?area_code=${encodeURIComponent(area)}`);
      setResults(r.numbers);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setSearching(false);
    }
  }

  async function assign(number: string, how: "purchase" | "import") {
    if (how === "purchase" && !window.confirm(`Buy ${number} from Twilio for this account? Twilio bills the platform account monthly.`)) return;
    setBusy(number);
    try {
      await post(url, { number, mode: how, request_id: openRequest?.id });
      setResults(null);
      await mutate();
      toast(`${number} assigned`);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function release(n: PhoneNumberItem) {
    const returnIt = n.source === "purchased" && window.confirm(`Release ${n.number} back to Twilio too? (OK = release and stop paying for it, Cancel = only remove it from this account)`);
    if (!returnIt && !window.confirm(`Remove ${n.number} from this account?`)) return;
    setBusy(n.id);
    try {
      await del(`/api/admin/phone-numbers/${n.id}?return_to_twilio=${returnIt}`);
      await mutate();
      toast(returnIt ? `${n.number} released to Twilio` : `${n.number} removed`);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function decline(id: string) {
    try {
      await post(`/api/admin/phone-number-requests/${id}/decline`);
      await mutate();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }

  const unassigned = (telephony?.owned ?? []).filter((o) => !o.org_id);

  return (
    <Card className="min-w-0">
      <CardHeader title="Phone numbers" description="Caller IDs for this account's calls" />
      {!data ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="flex flex-col gap-4 p-5">
          {data.numbers.length === 0 ? (
            <p className="text-sm text-zinc-500">No numbers — calls use the platform line.</p>
          ) : (
            <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              {data.numbers.map((n) => (
                <li key={n.id} className="flex items-center gap-2 px-3 py-2">
                  <Phone className="h-3.5 w-3.5 text-zinc-400" />
                  <span className="font-mono text-sm tabular-nums">{n.number}</span>
                  {n.is_default && <Badge tone="violet">Default</Badge>}
                  <Badge tone="gray">{n.carrier || "twilio"}</Badge>
                  <Badge tone="gray">{n.source}</Badge>
                  <button
                    type="button"
                    onClick={() => void release(n)}
                    disabled={busy === n.id}
                    className="ml-auto rounded p-1 text-zinc-400 hover:bg-red-50 hover:text-red-600"
                    aria-label={`Remove ${n.number}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {data.requests.map((r) => (
            <Notice key={r.id} tone="blue">
              Requested a number{r.area_code ? ` in ${r.area_code}` : ""}. Assigning one below marks it done.{" "}
              <button type="button" className="font-medium underline" onClick={() => void decline(r.id)}>
                Decline
              </button>
            </Notice>
          ))}

          {(
            <>
              <Tabs<Mode>
                value={mode}
                onChange={setMode}
                tabs={[
                  { value: "buy", label: "Buy new" },
                  { value: "import", label: "Assign existing" },
                ]}
              />
              {mode === "import" && telephony?.owned_warnings?.map((warning) => <Notice key={warning}>{warning}</Notice>)}
              {mode === "import" && <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-zinc-500">Assign numbers already owned in Twilio, Bandwidth or SignalWire. SignalWire currently supports outbound calls.</p><Button size="sm" onClick={() => void refreshSWR("/api/admin/telephony")}>Refresh numbers</Button></div>}
              {mode === "buy" && !data.twilio_ready ? <Notice>Twilio must be configured to buy numbers. Use Assign existing for SignalWire and Bandwidth.</Notice> : mode === "buy" ? (
                <>
                  <form onSubmit={search} className="flex items-end gap-2">
                    <Field label="Area code" className="flex-1">
                      <Input
                        value={area}
                        onChange={(e) => setArea(e.target.value.replace(/\D/g, "").slice(0, 3))}
                        placeholder={openRequest?.area_code || "e.g. 415"}
                        inputMode="numeric"
                      />
                    </Field>
                    <Button loading={searching} disabled={area.length !== 3}>
                      <Search className="h-4 w-4" /> Search
                    </Button>
                  </form>
                  {results && (
                    <ul className="max-h-64 divide-y divide-zinc-100 overflow-y-auto rounded-lg border border-zinc-200">
                      {results.length === 0 && <li className="px-3 py-3 text-sm text-zinc-500">None available — try a nearby area code.</li>}
                      {results.map((n) => (
                        <li key={n.number} className="flex items-center justify-between gap-2 px-3 py-2">
                          <span className="min-w-0">
                            <span className="font-mono text-sm tabular-nums">{n.friendly}</span>
                            <span className="ml-2 text-xs text-zinc-500">{[n.locality, n.region].filter(Boolean).join(", ")}</span>
                          </span>
                          <Button size="sm" variant="primary" onClick={() => void assign(n.number, "purchase")} loading={busy === n.number} disabled={!!busy}>
                            Buy
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : !telephony ? (
                <div className="flex justify-center py-4">
                  <Spinner />
                </div>
              ) : telephony.owned_error ? (
                <Notice tone="red">{telephony.owned_error}</Notice>
              ) : unassigned.length === 0 ? (
                <p className="text-sm text-zinc-500">No unassigned numbers found. Purchase numbers in your carrier dashboard, then refresh. SignalWire requires API credentials and a LiveKit trunk configured on the server.</p>
              ) : (
                <ul className="max-h-64 divide-y divide-zinc-100 overflow-y-auto rounded-lg border border-zinc-200">
                  {unassigned.map((o) => (
                    <li key={o.sid} className="flex items-center justify-between gap-2 px-3 py-2">
                      <span className="min-w-0">
                        <span className="font-mono text-sm tabular-nums">{o.number}</span>
                        <Badge tone="gray">{o.carrier || "twilio"}</Badge>
                        {o.friendly && <span className="ml-2 text-xs text-zinc-500">{o.friendly}</span>}
                      </span>
                      <Button size="sm" onClick={() => void assign(o.number, "import")} loading={busy === o.number} disabled={!!busy}>
                        Assign
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  );
}
