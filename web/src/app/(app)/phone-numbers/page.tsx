"use client";

import { Hash, Phone, Search, Star } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import MatteAlertFeedback from "@/components/ui/matte-alert-feedback";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Notice, PageHeader, Spinner } from "@/components/ui";
import { api, fetcher, patch, post } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import type { MyPhoneNumbers, PhoneNumberItem } from "@/lib/types";

interface Available {
  number: string;
  friendly: string;
  locality: string;
  region: string;
}

type Pricing = MyPhoneNumbers["pricing"];

/** What the next number costs: free while it's within the plan's included count, else the monthly add-on. */
function nextNumberCost(p: Pricing): { free: boolean; text: string } {
  if (!p) return { free: false, text: "" };
  const unit = `$${(p.unit_cents / 100).toFixed(2)}/mo`;
  if (!p.subscribed) return { free: false, text: `${unit} per number — no plan needed. Or get your first ${p.included_on_plan === 1 ? "number" : `${p.included_on_plan} numbers`} included with any plan.` };
  if (p.active < p.included) return { free: true, text: `Included with your plan — no extra charge. Extra numbers after that are ${unit} each.` };
  return { free: false, text: `You've used your included number. Each extra number is ${unit}, billed with your plan.` };
}

function PriceLine({ pricing }: { pricing: Pricing }) {
  const c = nextNumberCost(pricing);
  if (!c.text) return null;
  return <p className={`px-5 pb-4 text-xs ${c.free ? "text-emerald-700" : "text-zinc-500"}`}>{c.text}</p>;
}

function fmtDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }) : "";
}

export default function PhoneNumbersPage() {
  const { session } = useSession();
  const manager = canManage(session);
  const [returned, setReturned] = useState<"success" | "canceled" | null>(null);
  useEffect(() => {
    const v = new URLSearchParams(window.location.search).get("checkout");
    if (v === "success" || v === "canceled") setReturned(v);
  }, []);
  // Right after checkout, poll briefly while the payment webhook buys the number.
  const { data, mutate, error } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher, { refreshInterval: returned === "success" ? 3000 : 0 });

  if (error) return <Notice tone="red">{error.message}</Notice>;
  if (!data)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );

  const full = data.numbers.length >= data.max_numbers;

  return (
    <>
      {returned === "success" && (
        <div className="mb-4">
          <Notice tone="green">Payment received — your number is being added. It shows up below in a few seconds.</Notice>
        </div>
      )}
      {returned === "canceled" && (
        <div className="mb-4">
          <Notice tone="amber">Checkout was canceled — nothing was charged.</Notice>
        </div>
      )}
      <PageHeader title="Phone numbers" description="The numbers your agents call from. Pick a default, or set one per agent under Agent → Actions." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <NumbersList numbers={data.numbers} manager={manager} refresh={() => void mutate()} />
        {manager && (
          <div className="flex min-w-0 flex-col gap-6">
            {data.numbers.length === 0 && (
              <MatteAlertFeedback
                cardTitle="Caller ID"
                pillText="Shared line"
                cardDescription="Your calls go out from the shared BlackSync line until you add a number."
                alertTitle="Get your own number"
                alertDetail="A local number of your own gets more pickups, keeps your caller reputation separate, and lets contacts call you back."
                showControls={false}
                persistKey="phone-shared-line"
              />
            )}
            {full ? (
              <Card className="p-5 text-sm text-zinc-600">This account has reached its limit of {data.max_numbers} numbers. Contact support for more.</Card>
            ) : data.self_serve ? (
              <BuyNumber pricing={data.pricing} refresh={() => void mutate()} />
            ) : (
              <RequestNumber pricing={data.pricing} refresh={() => void mutate()} />
            )}
            {data.requests.length > 0 && (
              <Card>
                <CardHeader title="Your requests" />
                <ul className="divide-y divide-zinc-100">
                  {data.requests.map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                      <span className="text-zinc-700">{r.area_code ? `Area code ${r.area_code}` : "Any area code"}</span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-zinc-400">{fmtDate(r.created_at)}</span>
                        <Badge tone={r.status === "fulfilled" ? "green" : r.status === "declined" ? "red" : "amber"}>{r.status === "open" ? "pending" : r.status}</Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function NumbersList({ numbers, manager, refresh }: { numbers: PhoneNumberItem[]; manager: boolean; refresh: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function makeDefault(n: PhoneNumberItem) {
    setBusy(n.id);
    try {
      await patch(`/api/phone-numbers/${n.id}`, { is_default: true });
      refresh();
      toast(`${n.number} is now the default`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function rename(n: PhoneNumberItem, label: string) {
    if (label === n.label) return;
    try {
      await patch(`/api/phone-numbers/${n.id}`, { label });
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <Card className="min-w-0">
      <CardHeader title="Your numbers" description={numbers.length ? `${numbers.length} active` : undefined} />
      {numbers.length === 0 ? (
        <EmptyState
          icon={<Hash className="h-5 w-5" />}
          title="No numbers yet"
          description="Until you add one, your calls go out from the shared platform line."
        />
      ) : (
        <ul className="divide-y divide-zinc-100">
          {numbers.map((n) => (
            <li key={n.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <Phone className="h-4 w-4 shrink-0 text-zinc-400" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium tabular-nums text-zinc-900">{n.number}</span>
                  {n.is_default && <Badge tone="violet">Default</Badge>}
                </div>
                {manager ? (
                  <input
                    defaultValue={n.label}
                    placeholder="Add a label (e.g. Sales line)"
                    onBlur={(e) => void rename(n, e.target.value.trim())}
                    className="mt-0.5 w-full max-w-xs bg-transparent text-xs text-zinc-500 outline-none placeholder:text-zinc-300 focus:text-zinc-800"
                    aria-label={`Label for ${n.number}`}
                  />
                ) : (
                  n.label && <div className="text-xs text-zinc-500">{n.label}</div>
                )}
              </div>
              {manager && !n.is_default && (
                <Button size="sm" onClick={() => void makeDefault(n)} loading={busy === n.id}>
                  <Star className="h-3.5 w-3.5" /> Make default
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function RequestNumber({ pricing, refresh }: { pricing: Pricing; refresh: () => void }) {
  const toast = useToast();
  const [area, setArea] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await post("/api/phone-numbers/requests", { area_code: area.trim() });
      setArea("");
      refresh();
      toast("Request sent — we'll set up your number shortly");
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Get a number" description="Tell us the area code you want and we'll set it up for you." />
      <form onSubmit={submit} className="flex items-end gap-2 p-5">
        <Field label="Area code (optional)" className="flex-1">
          <Input value={area} onChange={(e) => setArea(e.target.value.replace(/\D/g, "").slice(0, 3))} placeholder="e.g. 689" inputMode="numeric" />
        </Field>
        <Button variant="primary" loading={busy}>
          Request number
        </Button>
      </form>
      <PriceLine pricing={pricing} />
    </Card>
  );
}

function BuyNumber({ pricing, refresh }: { pricing: Pricing; refresh: () => void }) {
  const toast = useToast();
  const [area, setArea] = useState("");
  const [results, setResults] = useState<Available[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [buying, setBuying] = useState<string | null>(null);

  async function search(e: FormEvent) {
    e.preventDefault();
    setSearching(true);
    try {
      const r = await api<{ numbers: Available[] }>(`/api/phone-numbers/available?area_code=${encodeURIComponent(area)}`);
      setResults(r.numbers);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setSearching(false);
    }
  }

  async function buy(n: Available) {
    const cost = nextNumberCost(pricing);
    const unit = pricing ? `$${(pricing.unit_cents / 100).toFixed(2)}/mo` : "$3.50/mo";
    const note = cost.free
      ? "It's included with your plan."
      : pricing && !pricing.subscribed
        ? `It's ${unit} — you'll pay securely with Stripe, then the number is added right away. Cancel any time in Billing.`
        : `It's billed at ${unit} with your plan.`;
    if (!window.confirm(`Add ${n.friendly} to this account? ${note}`)) return;
    setBuying(n.number);
    try {
      const r = await post<{ checkout_url?: string }>("/api/phone-numbers/purchase", { number: n.number });
      if (r?.checkout_url) {
        window.location.href = r.checkout_url;
        return;
      }
      setResults(null);
      setArea("");
      refresh();
      toast(`${n.friendly} added`);
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBuying(null);
    }
  }

  return (
    <Card>
      <CardHeader title="Get a number" description="Search by area code and add one instantly." />
      <form onSubmit={search} className="flex items-end gap-2 p-5 pb-3">
        <Field label="Area code" className="flex-1">
          <Input value={area} onChange={(e) => setArea(e.target.value.replace(/\D/g, "").slice(0, 3))} placeholder="e.g. 689" inputMode="numeric" />
        </Field>
        <Button loading={searching} disabled={area.length !== 3}>
          <Search className="h-4 w-4" /> Search
        </Button>
      </form>
      <PriceLine pricing={pricing} />
      {results && (
        <ul className="max-h-80 divide-y divide-zinc-100 overflow-y-auto border-t border-zinc-100">
          {results.length === 0 && <li className="px-5 py-4 text-sm text-zinc-500">No numbers available in that area code. Try a nearby one.</li>}
          {results.map((n) => (
            <li key={n.number} className="flex items-center justify-between gap-3 px-5 py-2.5">
              <div className="min-w-0">
                <div className="font-mono text-sm tabular-nums">{n.friendly}</div>
                <div className="text-xs text-zinc-500">{[n.locality, n.region].filter(Boolean).join(", ")}</div>
              </div>
              <Button size="sm" variant="primary" onClick={() => void buy(n)} loading={buying === n.number} disabled={!!buying}>
                Add
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
