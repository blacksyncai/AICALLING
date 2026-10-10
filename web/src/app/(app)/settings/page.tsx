"use client";

import { CheckCircle2, Circle, ExternalLink } from "lucide-react";
import useSWR from "swr";
import { Badge, Card, CardHeader, Notice, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { SettingsStatus } from "@/lib/types";

const INTEGRATIONS: {
  key: keyof SettingsStatus["integrations"];
  name: string;
  unlocks: string;
  env: string[];
  link: string;
  linkLabel: string;
}[] = [
  { key: "openai", name: "OpenAI", unlocks: "Chat playground, the agent's brain on calls, post-call summaries", env: ["OPENAI_API_KEY"], link: "https://platform.openai.com/api-keys", linkLabel: "Get API key" },
  { key: "livekit", name: "LiveKit", unlocks: "Real-time voice rooms (browser + phone calls)", env: ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"], link: "https://cloud.livekit.io", linkLabel: "Free LiveKit Cloud project" },
  { key: "deepgram", name: "Deepgram", unlocks: "Speech-to-text (hearing the caller)", env: ["DEEPGRAM_API_KEY"], link: "https://console.deepgram.com", linkLabel: "Get API key ($200 free)" },
  { key: "cartesia", name: "Cartesia", unlocks: "Text-to-speech voices + the voice library", env: ["CARTESIA_API_KEY"], link: "https://play.cartesia.ai/keys", linkLabel: "Get API key" },
  { key: "sip_trunk", name: "Phone line (SIP trunk)", unlocks: "Dialing real phone numbers, campaigns", env: ["LIVEKIT_SIP_OUTBOUND_TRUNK_ID"], link: "https://docs.livekit.io/sip/quickstarts/configuring-twilio-trunk/", linkLabel: "Twilio → LiveKit trunk guide" },
  { key: "calcom", name: "Cal.com (optional)", unlocks: "Real calendar bookings (mock slots are used otherwise)", env: ["CALCOM_API_KEY", "CALCOM_EVENT_TYPE_ID"], link: "https://app.cal.com/settings/developer/api-keys", linkLabel: "Get API key" },
];

const CAPS: { key: keyof SettingsStatus["capabilities"]; label: string; needs: string }[] = [
  { key: "chat_test", label: "Chat testing", needs: "OpenAI" },
  { key: "web_call", label: "Browser voice calls", needs: "OpenAI + LiveKit + Deepgram + Cartesia, and the worker running" },
  { key: "phone_call", label: "Phone calls & campaigns", needs: "Everything above + a SIP trunk" },
  { key: "post_call_analysis", label: "Post-call AI analysis", needs: "OpenAI" },
];

export default function SettingsPage() {
  const { session } = useSession();
  if (session && !session.user.is_superadmin) {
    return (
      <>
        <PageHeader title="Platform settings" />
        <Notice tone="blue">Platform settings are managed by your BlackSync admin. Your own details live under Profile & team.</Notice>
      </>
    );
  }
  return <PlatformSettings />;
}

function PlatformSettings() {
  const { data: s, error } = useSWR<SettingsStatus>("/api/settings/status", fetcher, { refreshInterval: 10000 });

  return (
    <>
      <PageHeader title="Platform settings" description="Connect providers by adding keys to backend/.env, then restart the API and worker." />
      {error && <Notice tone="red">Can&apos;t reach the backend: {error.message}</Notice>}
      {!s && !error && (
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      )}
      {s && (
        <div className="space-y-6">
          <Card>
            <CardHeader title="What works right now" />
            <div className="grid gap-px bg-zinc-100 sm:grid-cols-2">
              {CAPS.map((c) => (
                <div key={c.key} className="flex gap-3 bg-white p-4">
                  {s.capabilities[c.key] ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" /> : <Circle className="h-5 w-5 shrink-0 text-zinc-300" />}
                  <div>
                    <div className="text-sm font-medium">{c.label}</div>
                    <div className="text-xs text-zinc-500">Needs: {c.needs}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Integrations" description={`Database: ${s.database}${s.database === "sqlite" ? " (local file — set DATABASE_URL for Postgres in production)" : ""}`} />
            <div className="divide-y divide-zinc-100">
              {INTEGRATIONS.map((i) => (
                <div key={i.key} className="flex flex-wrap items-start gap-4 px-5 py-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{i.name}</span>
                      <Badge tone={s.integrations[i.key] ? "green" : "gray"}>{s.integrations[i.key] ? "Connected" : "Not set"}</Badge>
                    </div>
                    <div className="mt-0.5 text-xs text-zinc-500">{i.unlocks}</div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {i.env.map((e) => (
                        <code key={e} className="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-700">
                          {e}
                        </code>
                      ))}
                    </div>
                  </div>
                  <a href={i.link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
                    {i.linkLabel} <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Run it" description="Three processes: API, voice worker, web app." />
            <pre className="overflow-x-auto p-5 text-xs leading-relaxed text-zinc-700">{`# 1. API
cd backend && cp .env.example .env   # add your keys
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 2. Voice worker (needed for browser + phone calls)
python agent_worker.py download-files   # first time only
python agent_worker.py dev

# 3. Web app
cd web && npm install && npm run dev   # http://localhost:3000`}</pre>
            {s.capabilities.web_call && (
              <div className="px-5 pb-5">
                <Notice tone="blue">
                  Keys look good. If a voice test connects but the agent never speaks, the worker isn&apos;t running or is registered under a different name than{" "}
                  <code>{s.agent_name}</code> (LIVEKIT_AGENT_NAME).
                </Notice>
              </div>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
