"use client";

import { useEffect, useState } from "react";
import { post } from "@/lib/api";

/**
 * Billing-country pop-up. US (default) keeps paying through Stripe; Canadian and
 * other accounts pay through Helcim. The choice is remembered on the account —
 * we ask only until it's set, and it can be changed any time from the banner.
 */
export function CountryPopup({ open, onDone, onCancel, initial }: { open: boolean; onDone: (country: string) => void; onCancel: () => void; initial?: string | null }) {
  const [country, setCountry] = useState(initial || "US");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setCountry(initial || "US");
      setError(null);
      setBusy(false);
    }
  }, [open, initial]);

  if (!open) return null;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await post("/api/billing/country", { country });
      onDone(country);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const options: { key: string; label: string; sub: string }[] = [
    { key: "US", label: "United States", sub: "Pay in USD via Stripe" },
    { key: "CA", label: "Canada", sub: "Pay in USD via Helcim" },
    { key: "OTHER", label: "Other", sub: "Pay in USD via Helcim" },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <h3 className="font-display text-lg font-semibold text-zinc-900">Where is your business based?</h3>
        <p className="mt-1 text-sm text-zinc-500">
          We use this to pick the right payment processor. Prices are in USD either way.
        </p>
        <div className="mt-4 space-y-2">
          {options.map((o) => (
            <button
              key={o.key}
              type="button"
              onClick={() => setCountry(o.key)}
              className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition ${
                country === o.key ? "border-brand-600 bg-brand-50" : "border-zinc-200 hover:bg-zinc-50"
              }`}
            >
              <span
                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${
                  country === o.key ? "border-brand-600" : "border-zinc-300"
                }`}
              >
                {country === o.key && <span className="h-2 w-2 rounded-full bg-brand-600" />}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-zinc-900">{o.label}</span>
                <span className="block text-xs text-zinc-500">{o.sub}</span>
              </span>
            </button>
          ))}
        </div>
        {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-full px-4 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-100">
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={busy}
            className="rounded-full bg-gradient-to-br from-brand-500 to-brand-600 px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Saving…" : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
