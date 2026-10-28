"use client";

import { Clock, Hash, Phone, Search, ShieldCheck, Star } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { TextingCard } from "@/components/phone/TextingCard";
import { NumberPackCard } from "@/components/phone/NumberPackCard";
import MatteAlertFeedback from "@/components/ui/matte-alert-feedback";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Notice, PageHeader, Spinner } from "@/components/ui";
import { api, fetcher, patch, post } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import type { MyPhoneNumbers, PhoneNumberItem } from "@/lib/types";

import { searchNumberInventory, type AvailableNumber as Available } from "@/lib/number-search";

type Pricing = MyPhoneNumbers["pricing"];

/** What the next number costs: free while it's within the plan's included count, else the monthly add-on. */
function nextNumberCost(p: Pricing): { free: boolean; text: string } {
  if (!p) return { free: false, text: "" };
  const unit = `$${(p.unit_cents / 100).toFixed(2)}/mo`;
  if (!p.subscribed) return { free: false, text: `${unit} per number — no plan needed. Or get 1–4 numbers included with a plan.` };
  if (p.active < p.included) return { free: true, text: `Included with your plan — no extra charge. Extra numbers after that are ${unit} each.` };
  if (p.pack_credits)
    return { free: true, text: `Uses 1 of your ${p.pack_credits} Fresh Number Pack credit${p.pack_credits === 1 ? "" : "s"} — no extra charge. It's swapped for a fresh number in the same area code every month.` };
  return { free: false, text: `You've used your plan's ${p.included === 1 ? "included number" : `${p.included} included numbers`}. Each extra number is ${unit}, charged now (prorated) and with your plan each month.` };
}

function PriceLine({ pricing }: { pricing: Pricing }) {
  const c = nextNumberCost(pricing);
  if (!c.text) return null;
  return <p className={`text-xs ${c.free ? "text-emerald-300" : "text-zinc-400"}`}>{c.text}</p>;
}

/** The "Get a number" call to action: a dark card with an orange glow so it stands out on the page. */
function GetNumberCard({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section id="get-number" className="relative scroll-mt-6 overflow-hidden rounded-2xl bg-zinc-950 text-white shadow-lg ring-1 ring-zinc-900">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(420px_220px_at_100%_0%,rgba(236,101,60,0.45),transparent_70%),radial-gradient(360px_200px_at_0%_100%,rgba(245,158,11,0.18),transparent_70%)]"
      />
      <div className="relative flex flex-col gap-4 p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-600 shadow-[0_6px_20px_-6px_rgba(236,101,60,0.8)]">
            <Phone className="h-5 w-5 text-white" />
          </span>
          <div>
            <h2 className="font-display text-lg font-semibold tracking-tight">{title}</h2>
            <p className="mt-0.5 text-sm text-zinc-300">{description}</p>
          </div>
        </div>
        {children}
      </div>
    </section>
  );
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
    if (v === "success" || v === "canceled") {
      setReturned(v);
      window.history.replaceState(null, "", window.location.pathname); // a reload shouldn't repeat it
    }
  }, []);
  // Right after checkout, poll for a minute while the payment webhook buys the number.
  const [polling, setPolling] = useState(false);
  useEffect(() => {
    if (returned !== "success") return;
    setPolling(true);
    const t = setTimeout(() => setPolling(false), 60_000);
    return () => clearTimeout(t);
  }, [returned]);
  const { data, mutate, error } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher, { refreshInterval: polling ? 3000 : 30000 });

  if (error) return <Notice tone="red">{error.message}</Notice>;
  if (!data)
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );

  const getNumber = data.self_serve ? (
    <BuyNumber carriers={data.purchase_carriers || ["twilio"]} pricing={data.pricing} refresh={() => void mutate()} />
  ) : (
    <RequestNumber pricing={data.pricing} refresh={() => void mutate()} />
  );

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
      {manager && data.numbers.length === 0 && <div className="mb-6">{getNumber}</div>}
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
            {data.numbers.length > 0 && getNumber}
            <NumberPackCard onChanged={() => void mutate()} />
            <TextingCard />
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

  async function resume(n: PhoneNumberItem) {
    setBusy(n.id);
    try {
      await post(`/api/phone-numbers/${n.id}/resume`, {});
      refresh();
      toast(`${n.number} is back in rotation`);
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
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium tabular-nums text-zinc-900">{n.number}</span>
                  {n.is_default && <Badge tone="violet">Default</Badge>}
                  {n.pack_refresh_at && (
                    <span title="Part of your Fresh Number Pack: swapped for a new number on this date">
                      <Badge tone="amber">Fresh pack · new number {fmtDate(n.pack_refresh_at)}</Badge>
                    </span>
                  )}
                  {n.registration && <span className="text-xs text-zinc-500">{n.registration.status}</span>}
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
                <SpamProtection n={n} />
                <NumberHealth n={n} />
              </div>
              {manager && n.health?.resting_until && (
                <Button size="sm" onClick={() => void resume(n)} loading={busy === n.id}>
                  Put back in rotation
                </Button>
              )}
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

/** Plivo numbers are registered with AT&T and T-Mobile automatically so calls are less likely to show "Spam Likely". */
function SpamProtection({ n }: { n: PhoneNumberItem }) {
  const p = n.spam_protection;
  if (!p) return null;
  const carrierName = (c: string) => (c === "at&t" ? "AT&T" : c === "t-mobile" ? "T-Mobile" : c);
  if (p.status === "ACTIVE") {
    const on = Object.entries(p.carriers).filter(([, v]) => v.status === "ACTIVE").map(([c]) => carrierName(c));
    return (
      <div className="mt-1 flex items-center gap-1.5 text-xs text-emerald-700">
        <ShieldCheck className="h-3.5 w-3.5" /> Spam protection active{on.length ? ` · ${on.join(", ")}` : ""}
      </div>
    );
  }
  if (p.status === "FAILED") {
    const why = Object.values(p.carriers).find((v) => v.status === "FAILED")?.reason;
    return (
      <div className="mt-1 text-xs text-red-600">
        Spam protection registration didn&apos;t go through{why ? `: ${why}` : ""}. We&apos;ll retry — message us in the chat if it stays.
      </div>
    );
  }
  return (
    <div className="mt-1 flex items-center gap-1.5 text-xs text-amber-700">
      <Clock className="h-3.5 w-3.5" /> Registering with AT&amp;T and T-Mobile for spam protection — give us a few hours.
    </div>
  );
}

/** One line of call health: dials, pickup rate, and a warning when the number is likely labeled spam. */
function NumberHealth({ n }: { n: PhoneNumberItem }) {
  const h = n.health;
  if (!h || h.dials_7d === 0) return <div className="mt-1 text-xs text-zinc-400">No outbound calls in the last 7 days</div>;
  const rate = h.pickup_rate === null ? "—" : `${Math.round(h.pickup_rate * 100)}%`;
  return (
    <div className="mt-1 space-y-1">
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums text-zinc-500">
        <span>
          <span className="font-medium text-zinc-700">{rate}</span> picked up
        </span>
        <span>{h.dials_7d} calls this week</span>
        <span>{h.dials_24h} in the last 24h</span>
        {h.avg_talk_seconds > 0 && <span>{h.avg_talk_seconds}s avg talk</span>}
      </div>
      {h.resting_until ? (
        <div className="text-xs text-amber-700">
          Resting from campaigns until {new Date(h.resting_until).toLocaleDateString()} — pickups dropped well below your other numbers, so it may be
          labeled spam. Dispute it, then put it back in rotation.
        </div>
      ) : (
        h.low_pickups && (
          <div className="text-xs text-amber-700">Pickups are well below your other numbers — it may be labeled spam.</div>
        )
      )}
    </div>
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
    <GetNumberCard title="Get a local number" description="Tell us the area code you want and we'll set it up for you.">
      <form onSubmit={submit} className="flex items-center gap-2">
        <Input
          value={area}
          onChange={(e) => setArea(e.target.value.replace(/\D/g, "").slice(0, 3))}
          placeholder="Area code, e.g. 689"
          inputMode="numeric"
          aria-label="Area code"
          className="h-11 flex-1 bg-white text-zinc-900"
        />
        <Button variant="primary" loading={busy} className="h-11 shrink-0 rounded-xl! px-5">
          Request number
        </Button>
      </form>
      <PriceLine pricing={pricing} />
    </GetNumberCard>
  );
}

function BuyNumber({ pricing, refresh, carriers }: { pricing: Pricing; refresh: () => void; carriers: string[] }) {
  const toast = useToast();
  const [area, setArea] = useState("");
  const [results, setResults] = useState<Available[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [buying, setBuying] = useState<string | null>(null);
  // Numbered options, never provider names: 1 is the default, the rest are alternatives.
  const [line, setLine] = useState(0);
  const pick = Math.min(line, Math.max(carriers.length - 1, 0));
  const searchCarriers = carriers.length ? [carriers[pick]] : [];

  async function search(e: FormEvent) {
    e.preventDefault();
    setSearching(true);
    setResults(null);
    try {
      const numbers = await searchNumberInventory(searchCarriers, (carrier) =>
        api<{ numbers: Available[] }>(`/api/phone-numbers/available?area_code=${encodeURIComponent(area)}&carrier=${encodeURIComponent(carrier)}`),
      );
      setResults(numbers);
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
      ? pricing?.active != null && pricing.active < pricing.included ? "It's included with your plan." : "It uses 1 Fresh Number Pack credit (no extra charge)."
      : pricing && !pricing.subscribed
        ? `It's ${unit} — you'll pay securely with Stripe, then the number is added right away. Cancel any time in Billing.`
        : `It's ${unit}: the prorated amount for this month is charged to your card now, then it's billed with your plan.`;
    if (!window.confirm(`Add ${n.friendly} to this account? ${note}`)) return;
    setBuying(n.number);
    try {
      // confirm_charge: the customer just saw and accepted the price above.
      const r = await post<{ checkout_url?: string; used_pack_credit?: boolean }>("/api/phone-numbers/purchase", { number: n.number, carrier: n.carrier, confirm_charge: !cost.free });
      if (r?.checkout_url) {
        window.location.href = r.checkout_url;
        return; // stays busy while the browser leaves for checkout
      }
      setResults(null);
      setArea("");
      refresh();
      toast(r?.used_pack_credit ? `${n.friendly} added with a pack credit` : `${n.friendly} added`);
      setBuying(null);
    } catch (err) {
      toast((err as Error).message, "error");
      setBuying(null);
    }
  }

  return (
    <GetNumberCard title="Get a local number" description="Choose a local number for outbound calls.">
      {carriers.length > 1 && (
        <div className="flex gap-2" role="radiogroup" aria-label="Number option">
          {carriers.map((c, i) => (
            <button
              key={c}
              type="button"
              role="radio"
              aria-checked={pick === i}
              onClick={() => { setLine(i); setResults(null); }}
              className={`h-9 rounded-lg px-4 text-sm font-medium ring-1 ${pick === i ? "bg-white text-zinc-900 ring-white" : "bg-transparent text-zinc-300 ring-white/30 hover:ring-white/60"}`}
            >
              {i + 1}
            </button>
          ))}
        </div>
      )}
      <form onSubmit={search} className="flex items-center gap-2">
        <Input
          value={area}
          onChange={(e) => setArea(e.target.value.replace(/\D/g, "").slice(0, 3))}
          placeholder="Area code, e.g. 689"
          inputMode="numeric"
          aria-label="Area code"
          className="h-11 flex-1 bg-white text-zinc-900"
        />
        <Button variant="primary" loading={searching} disabled={area.length !== 3 || !!buying} className="h-11 shrink-0 rounded-xl! px-5">
          <Search className="h-4 w-4" /> Search numbers
        </Button>
      </form>
      <PriceLine pricing={pricing} />
      {results && (
        <ul className="max-h-80 divide-y divide-zinc-100 overflow-y-auto rounded-xl bg-white text-zinc-900">
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
    </GetNumberCard>
  );
}
