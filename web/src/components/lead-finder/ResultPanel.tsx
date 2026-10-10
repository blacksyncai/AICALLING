"use client";

import { Check, Copy, Mail, Phone, ShieldAlert, Trash2, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card } from "@/components/ui";
import type { Lookup, LookupPhone, PlaceAddress } from "./types";

function oneLine(a: PlaceAddress | undefined) {
  if (!a) return "";
  const tail = [a.state, a.zip].filter(Boolean).join(" ");
  return [a.address, a.city, tail].filter(Boolean).join(", ");
}

export function CopyButton({ value, label }: { value: string; label: string }) {
  const toast = useToast();
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {
          toast("Couldn't copy — select it and copy manually", "error");
        }
      }}
      className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
      aria-label={`Copy ${label}`}
      title="Copy"
    >
      {done ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 py-1 text-sm">
      <dt className="w-24 shrink-0 text-zinc-500">{label}</dt>
      <dd className="min-w-0 break-words text-zinc-900">{value || <span className="text-zinc-400">—</span>}</dd>
    </div>
  );
}

/** One lookup's result: property, owner and contact details with DNC flags. */
export function ResultPanel({
  lookup,
  cached,
  onSave,
  saving,
  onDelete,
}: {
  lookup: Lookup;
  cached?: boolean;
  onSave: () => void;
  saving: boolean;
  onDelete: () => void;
}) {
  const a = lookup.address;
  const searched = [a.street, a.city, [a.state, a.zip].filter(Boolean).join(" ")].filter(Boolean).join(", ");
  const r = lookup.result;

  if (lookup.deleted) {
    return (
      <Card className="p-5 text-sm text-zinc-600">
        The details for <span className="font-medium text-zinc-900">{searched}</span> were deleted.
      </Card>
    );
  }

  if (!lookup.found || !r) {
    return (
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="gray">No match</Badge>
          <span className="text-sm text-zinc-500">{searched}</span>
        </div>
        <p className="mt-2 text-sm font-medium text-zinc-900">No owner information found for this address.</p>
        <p className="mt-1 text-xs text-zinc-500">Check the street, city, state and ZIP — small differences like a missing unit number can affect the match.</p>
      </Card>
    );
  }

  const c = r.contact;
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 px-5 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge tone="green">Owner found</Badge>
          <span className="truncate text-sm font-medium text-zinc-900">{c.full_name || "Owner"}</span>
          {cached && <span className="text-xs text-zinc-400">Saved result — no lookup used</span>}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onDelete} className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-red-600" aria-label="Delete this result" title="Delete result">
            <Trash2 className="h-4 w-4" />
          </button>
          {lookup.lead_id ? (
            <Link href="/contacts" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
              <Check className="h-3.5 w-3.5 text-emerald-600" /> Saved to Contacts
            </Link>
          ) : (
            <Button size="sm" variant="primary" onClick={onSave} loading={saving}>
              <UserPlus className="h-3.5 w-3.5" /> Save as Lead
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-5 p-5 md:grid-cols-2">
        <Section title="Property">
          <dl>
            <Row label="Address" value={c.property.address || a.street} />
            <Row label="City" value={c.property.city || a.city} />
            <Row label="State" value={c.property.state || a.state} />
            <Row label="ZIP" value={c.property.zip || a.zip} />
          </dl>
        </Section>
        <Section title="Owner">
          <dl>
            <Row label="Full name" value={c.full_name} />
            <Row label="First name" value={c.first_name} />
            <Row label="Last name" value={c.last_name} />
            <Row label="Mailing" value={oneLine(c.mailing)} />
          </dl>
        </Section>

        <Section title="Phone numbers">
          {r.phones.length === 0 ? (
            <p className="text-sm text-zinc-500">No phone numbers available.</p>
          ) : (
            <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              {r.phones.map((p) => (
                <li key={p.number} className="flex flex-wrap items-center gap-2 px-3 py-2">
                  <Phone className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                  <span className="font-mono text-sm tabular-nums text-zinc-900">{p.display}</span>
                  <CopyButton value={p.number} label={`phone ${p.display}`} />
                  <span className="text-xs capitalize text-zinc-500">{p.type === "unknown" ? "Type unknown" : p.type}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Email addresses">
          {r.emails.length === 0 ? (
            <p className="text-sm text-zinc-500">No email addresses available.</p>
          ) : (
            <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              {r.emails.map((e) => (
                <li key={e} className="flex items-center gap-2 px-3 py-2">
                  <Mail className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                  <span className="min-w-0 truncate text-sm text-zinc-900">{e}</span>
                  <CopyButton value={e} label={`email ${e}`} />
                </li>
              ))}
            </ul>
          )}
        </Section>
        {r.phones.length > 0 && (
          <Section title="Do Not Call (reported by DataSkip)">
            <DncReport phones={r.phones} />
          </Section>
        )}
      </div>
    </Card>
  );
}

/** Provider-reported DNC flags, kept apart from the contact details and never applied automatically. */
function DncReport({ phones }: { phones: LookupPhone[] }) {
  const flagged = phones.filter((p) => p.dnc === true);
  const unknown = phones.filter((p) => p.dnc === null || p.dnc === undefined);
  return (
    <div className="rounded-lg border border-zinc-200 px-3 py-2.5 text-sm">
      {flagged.length === 0 ? (
        <p className="text-zinc-600">DataSkip didn&apos;t flag any of these numbers.</p>
      ) : (
        <ul className="space-y-1">
          {flagged.map((p) => (
            <li key={p.number} className="flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 text-amber-600" />
              <span className="font-mono tabular-nums">{p.display}</span>
              <Badge tone="amber">Flagged</Badge>
            </li>
          ))}
        </ul>
      )}
      {unknown.length > 0 && <p className="mt-1 text-xs text-zinc-500">{unknown.length} number{unknown.length === 1 ? "" : "s"} had no DNC status reported.</p>}
      <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
        Shown as reported by the provider — not verified. Run your own DNC scrub and check consent before calling.
      </p>
    </div>
  );
}
