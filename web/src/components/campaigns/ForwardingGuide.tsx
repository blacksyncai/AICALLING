"use client";

import { Check, Copy, PhoneForwarded } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

type Mode = "all" | "missed";
interface Carrier {
  key: string;
  label: string;
  /** Dial codes; `{n}` = the 10-digit BlackSync number. */
  all?: { on: string; off: string };
  missed?: { on: string; off: string; note?: string };
  steps?: string[];
  note?: string;
}

const CARRIERS: Carrier[] = [
  {
    key: "verizon",
    label: "Verizon",
    all: { on: "*72{n}", off: "*73" },
    missed: { on: "*71{n}", off: "*73", note: "Forwards calls you don't answer or decline." },
  },
  {
    key: "att",
    label: "AT&T",
    all: { on: "**21*1{n}#", off: "##21#" },
    missed: { on: "**61*1{n}#", off: "##61#", note: "No answer. For busy calls also dial **67*1{n}#." },
    note: "On iPhone you can also use Settings → Phone → Call Forwarding.",
  },
  {
    key: "tmobile",
    label: "T-Mobile",
    all: { on: "**21*1{n}#", off: "##21#" },
    missed: { on: "**61*1{n}#", off: "##61#", note: "No answer. Busy: **67*1{n}#, unreachable: **62*1{n}#." },
  },
  {
    key: "landline",
    label: "Business landline",
    all: { on: "*72{n}", off: "*73" },
    missed: { on: "*92{n}", off: "*93", note: "Codes for Comcast Business, Spectrum, Verizon Fios and most US landlines. Busy: *90{n} (off *91)." },
    note: "Lift the handset, dial the code, wait for the confirmation tone (or for the BlackSync line to ring), then hang up.",
  },
  {
    key: "voip",
    label: "RingCentral / Google Voice / Dialpad",
    steps: [
      "Open your phone system's admin or app settings.",
      "Find Call handling / Call forwarding (RingCentral: Settings → Call Handling & Forwarding; Google Voice: Settings → Calls → Call forwarding; Dialpad: Your settings → Call routing).",
      "Add the BlackSync number as a forwarding destination — for everything, or only after a few rings.",
      "Save, then call your business number from another phone to test.",
    ],
  },
];

const digits10 = (e164: string) => e164.replace(/\D/g, "").replace(/^1(?=\d{10}$)/, "");
const pretty = (e164: string) => {
  const d = digits10(e164);
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : e164;
};

function Code({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(code);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-3 py-2 font-mono text-base tracking-wide text-white transition-colors hover:bg-zinc-800"
      title="Copy"
    >
      {code}
      {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4 text-zinc-400" />}
    </button>
  );
}

/** How to forward a business or cell line to the BlackSync number, per carrier. */
export function ForwardingGuide({ number }: { number: string }) {
  const [carrier, setCarrier] = useState("verizon");
  const [mode, setMode] = useState<Mode>("missed");
  const c = CARRIERS.find((x) => x.key === carrier) ?? CARRIERS[0];
  const n = digits10(number);
  const fill = (s: string) => s.replaceAll("{n}", n);
  const codes = mode === "all" ? c.all : c.missed;

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <PhoneForwarded className="h-4 w-4" />
        </span>
        <div>
          <div className="text-sm font-semibold text-zinc-900">Forward your existing line to {pretty(number)}</div>
          <p className="mt-0.5 text-xs text-zinc-500">
            Keep your current business number. Forward it here and the agent answers — every call, or only the ones you miss.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {CARRIERS.map((x) => (
          <button
            key={x.key}
            type="button"
            onClick={() => setCarrier(x.key)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              carrier === x.key ? "border-brand-500 bg-brand-50 font-medium text-brand-700" : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300",
            )}
          >
            {x.label}
          </button>
        ))}
      </div>

      {c.steps ? (
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-zinc-700">
          {c.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      ) : (
        <>
          <div className="inline-flex rounded-lg bg-zinc-100 p-0.5 text-xs">
            {(["missed", "all"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={cn("rounded-md px-3 py-1.5 font-medium", mode === m ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500")}
              >
                {m === "missed" ? "Only calls I miss" : "Every call"}
              </button>
            ))}
          </div>
          {codes && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <div className="mb-1.5 text-xs font-medium text-zinc-700">Turn on — dial this from the phone you&apos;re forwarding</div>
                <Code code={fill(codes.on)} />
              </div>
              <div>
                <div className="mb-1.5 text-xs font-medium text-zinc-700">Turn off</div>
                <Code code={fill(codes.off)} />
              </div>
            </div>
          )}
          {mode === "missed" && c.missed?.note && <p className="text-xs text-zinc-500">{fill(c.missed.note)}</p>}
          {c.note && <p className="text-xs text-zinc-500">{c.note}</p>}
        </>
      )}

      <ul className="space-y-1 rounded-lg bg-zinc-50 px-3 py-2.5 text-xs text-zinc-600 ring-1 ring-zinc-100">
        <li>• Test it: call your business number from another phone — the agent should pick up.</li>
        <li>• iPhone users: turn off Live Voicemail (Settings → Phone) or it can catch calls before they forward.</li>
        <li>• Codes can differ by plan or prepaid brand (Visible, Cricket, Metro). If one doesn&apos;t work, your carrier&apos;s support can turn on forwarding for you.</li>
        <li>• Forwarded minutes are billed like any inbound call (AI time + the phone line fee).</li>
      </ul>
    </div>
  );
}
