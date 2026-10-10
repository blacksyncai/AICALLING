"use client";

import { Card, CardHeader } from "@/components/ui";

export function ZapierCard() {
  return (
    <Card>
      <CardHeader title="Connect Zapier" description="Works the same way with Make and n8n." />
      <div className="p-5">
        <div className="text-sm font-medium text-zinc-900">Send booked meetings to your CRM, Slack or calendar</div>
        <Steps
          items={[
            <>
              In Zapier, start a new Zap and choose <strong className="font-medium text-zinc-800">Webhooks by Zapier → Catch Hook</strong>. Copy the URL it gives you.
            </>,
            <>
              Here, click <strong className="font-medium text-zinc-800">Add webhook</strong>, paste the URL and pick what to send — for example <strong className="font-medium text-zinc-800">Meeting booked</strong>.
            </>,
            <>
              Click <strong className="font-medium text-zinc-800">Send test</strong>, then finish your Zap in Zapier with the app you want the details in.
            </>,
          ]}
        />
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
