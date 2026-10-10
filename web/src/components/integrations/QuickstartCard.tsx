"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/ui";
import { cn } from "@/lib/utils";
import { CodeBlock, CopyButton } from "./shared";

const ENDPOINTS: { method: "GET" | "POST"; path: string; desc: React.ReactNode }[] = [
  { method: "GET", path: "/me", desc: "Test a key — returns the account it belongs to" },
  { method: "GET", path: "/agents", desc: "List your agents" },
  { method: "GET", path: "/campaigns", desc: "List your campaigns" },
  { method: "GET", path: "/contacts?phone=", desc: "Look up a contact by phone number" },
  {
    method: "POST",
    path: "/contacts",
    desc: (
      <>
        Add a contact. Optional <Code>campaign_id</Code>, or <Code>call_with_agent_id</Code> to call them right away
      </>
    ),
  },
  {
    method: "POST",
    path: "/calls",
    desc: (
      <>
        Start a call: <Code>{"{agent_id, contact_id | to_phone}"}</Code>
      </>
    ),
  },
  { method: "GET", path: "/calls", desc: "List recent calls" },
  { method: "GET", path: "/calls/{id}", desc: "Get one call — status, outcome, summary" },
];

const SAMPLE_PAYLOAD = JSON.stringify(
  {
    id: "evt_…",
    event: "call.completed",
    created_at: "…",
    data: {
      call_id: "…",
      status: "completed",
      outcome: "meeting_booked",
      summary: "…",
      sentiment: "positive",
      duration_seconds: 142,
      to_phone: "+14155550123",
      contact: { id: "…", name: "Jamie Rivera", phone: "+14155550123", email: "jamie@globex.com", company: "Globex" },
      agent_name: "Outbound Sales SDR",
      campaign_name: "Q4 outbound",
      meeting_time: "Tuesday 2pm",
      extracted_data: {},
    },
  },
  null,
  2,
);

function Code({ children }: { children: React.ReactNode }) {
  return <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[11px] text-zinc-700">{children}</code>;
}

function useBaseUrl() {
  // window isn't available during SSR; fill it in after mount to avoid a hydration mismatch.
  const [base, setBase] = useState("https://your-blacksync-domain/api/v1");
  useEffect(() => setBase(`${window.location.origin}/api/v1`), []);
  return base;
}

export function QuickstartCard() {
  const base = useBaseUrl();

  const curlCall = `curl -X POST ${base}/contacts \\
  -H "Authorization: Bearer bsk_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Jamie Rivera",
    "phone": "+14155550123",
    "email": "jamie@globex.com",
    "company": "Globex",
    "call_with_agent_id": "AGENT_ID"
  }'`;

  const curlList = `curl ${base}/calls \\
  -H "Authorization: Bearer bsk_your_key"`;

  return (
    <Card>
      <CardHeader title="API quickstart" description="A small REST API for adding contacts, starting calls and reading results." />
      <div className="space-y-6 p-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="min-w-0">
            <div className="mb-1 text-xs font-medium text-zinc-700">Base URL</div>
            <div className="flex items-center gap-1 rounded-lg border border-zinc-200 bg-zinc-50 py-1 pl-3 pr-1">
              <code className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-800">{base}</code>
              <CopyButton text={base} />
            </div>
          </div>
          <div className="min-w-0">
            <div className="mb-1 text-xs font-medium text-zinc-700">Auth header</div>
            <div className="flex items-center gap-1 rounded-lg border border-zinc-200 bg-zinc-50 py-1 pl-3 pr-1">
              <code className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-800">Authorization: Bearer bsk_…</code>
              <CopyButton text="Authorization: Bearer " />
            </div>
          </div>
        </div>

        <div>
          <div className="mb-2 text-xs font-medium text-zinc-700">Endpoints</div>
          <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
            {ENDPOINTS.map((e) => (
              <li key={e.method + e.path} className="flex flex-col gap-1 px-3 py-2.5 sm:flex-row sm:items-baseline sm:gap-3">
                <span className="flex shrink-0 items-baseline gap-2 sm:w-52">
                  <span
                    className={cn(
                      "w-10 shrink-0 rounded px-1 py-0.5 text-center font-mono text-[10px] font-semibold",
                      e.method === "GET" ? "bg-blue-50 text-blue-700" : "bg-emerald-50 text-emerald-700",
                    )}
                  >
                    {e.method}
                  </span>
                  <code className="break-all font-mono text-xs text-zinc-900">{e.path}</code>
                </span>
                <span className="text-xs text-zinc-500">{e.desc}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="min-w-0">
            <div className="mb-2 text-xs font-medium text-zinc-700">Add a contact and call them right away</div>
            <CodeBlock code={curlCall} title="bash" />
          </div>
          <div className="min-w-0">
            <div className="mb-2 text-xs font-medium text-zinc-700">List recent calls</div>
            <CodeBlock code={curlList} title="bash" />
          </div>
        </div>

        <div className="min-w-0">
          <div className="mb-2 text-xs font-medium text-zinc-700">
            Sample <Code>call.completed</Code> webhook payload
          </div>
          <CodeBlock code={SAMPLE_PAYLOAD} title="json" />
        </div>
      </div>
    </Card>
  );
}

export function ZapierCard() {
  const base = useBaseUrl();
  return (
    <Card>
      <CardHeader title="Zapier setup" description="The same approach works in Make (HTTP module) and n8n (Webhook / HTTP Request nodes)." />
      <div className="grid gap-px bg-zinc-100 md:grid-cols-2">
        <div className="bg-white p-5">
          <div className="text-sm font-medium text-zinc-900">Trigger a Zap from BlackSync</div>
          <p className="mt-0.5 text-xs text-zinc-500">e.g. push booked meetings into your CRM or Slack.</p>
          <Steps
            items={[
              <>
                In Zapier, create a Zap with <strong className="font-medium text-zinc-800">Webhooks by Zapier → Catch Hook</strong> and copy its URL.
              </>,
              <>
                Click <strong className="font-medium text-zinc-800">Add webhook</strong> above, paste the URL and pick events (e.g. <Code>meeting.booked</Code>).
              </>,
              <>
                Hit <strong className="font-medium text-zinc-800">Send test</strong>, then in Zapier click “Test trigger” to load the sample fields and map them.
              </>,
            ]}
          />
        </div>
        <div className="bg-white p-5">
          <div className="text-sm font-medium text-zinc-900">Call leads from a Zap</div>
          <p className="mt-0.5 text-xs text-zinc-500">e.g. phone every new form submission within seconds.</p>
          <Steps
            items={[
              <>
                Create an API key above. Add a <strong className="font-medium text-zinc-800">Webhooks by Zapier → POST</strong> action with URL{" "}
                <code className="break-all rounded bg-zinc-100 px-1 py-0.5 font-mono text-[11px] text-zinc-700">{base}/contacts</code> and payload type JSON.
              </>,
              <>
                Add header <Code>Authorization</Code> = <Code>Bearer bsk_…</Code>, then map <Code>name</Code>, <Code>phone</Code> and{" "}
                <Code>call_with_agent_id</Code> (or <Code>campaign_id</Code>).
              </>,
            ]}
          />
        </div>
      </div>
    </Card>
  );
}

function Steps({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="mt-4 space-y-3">
      {items.map((item, i) => (
        <li key={i} className="flex gap-3 text-xs leading-relaxed text-zinc-600">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full brand-gradient text-[11px] font-semibold text-white">{i + 1}</span>
          <span className="min-w-0">{item}</span>
        </li>
      ))}
    </ol>
  );
}
