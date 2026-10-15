import Link from "next/link";
import { Logo } from "@/components/Logo";

const SERVER = "https://blacksync.si/api/mcp";

const STEPS: { app: string; steps: string[] }[] = [
  {
    app: "ChatGPT",
    steps: [
      "Open Settings → Apps & Connectors (turn on Developer mode under Advanced if your plan asks for it).",
      "Choose Create / Add connector, name it BlackSync and paste the server URL below. Authentication: OAuth.",
      "Sign in to BlackSync when asked and click Allow.",
      "In a chat, pick BlackSync from the tools menu and ask, for example: “Set up my BlackSync account and build me an agent.”",
    ],
  },
  {
    app: "Claude",
    steps: [
      "Open Settings → Connectors and choose Add custom connector.",
      "Name it BlackSync and paste the server URL below.",
      "Click Connect, sign in to BlackSync and click Allow.",
      "Turn BlackSync on in a chat's tools menu and ask what you need.",
    ],
  },
];

export const metadata = { title: "Connect BlackSync to ChatGPT or Claude" };

/** Public: how to add the BlackSync connector to an AI assistant. */
export default function ConnectHelpPage() {
  return (
    <main className="min-h-screen bg-zinc-50 px-4 py-10">
      <div className="mx-auto max-w-2xl space-y-6">
        <Logo />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Use BlackSync from ChatGPT or Claude</h1>
          <p className="mt-2 text-sm leading-relaxed text-zinc-600">
            Connect your BlackSync account to your AI assistant to set up your account, build and edit agents, add
            knowledge and contacts, run campaigns, place test calls and review call results, all from a chat.
          </p>
        </div>
        <div className="rounded-2xl border border-zinc-200 bg-white p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Server URL</div>
          <code className="mt-1 block break-all text-sm text-zinc-900">{SERVER}</code>
        </div>
        {STEPS.map((s) => (
          <div key={s.app} className="rounded-2xl border border-zinc-200 bg-white p-5">
            <h2 className="font-semibold text-zinc-900">{s.app}</h2>
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-zinc-700">
              {s.steps.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ol>
          </div>
        ))}
        <p className="text-sm text-zinc-500">
          The assistant acts as you, with your permissions, and asks before placing calls or starting campaigns. See or
          remove connected assistants under{" "}
          <Link href="/integrations" className="font-medium text-brand-700 hover:underline">
            Integrations
          </Link>
          .
        </p>
      </div>
    </main>
  );
}
