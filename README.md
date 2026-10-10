# BlackSync

**Build AI calling agents, test them in your browser in seconds, then let them work through your lead list.**

BlackSync's AI voice-agent platform: create agents from templates, give them a prompt,
knowledge base, voice and actions (book meetings, transfer to a human), talk to them right in the browser,
then upload a CSV and run outbound calling campaigns with transcripts, AI summaries and extracted data for
every call.

> Forked from [Pounce](https://github.com/Ashishlathkar77) (a single hard-coded SDR agent) and rebuilt into a
> multi-agent platform. The original Paul/Hemut agent still runs for any call without an agent config.

## What you get

| | |
|---|---|
| **Agent builder** | Templates (Sales SDR, Appointment Setter, Real Estate, Support Receptionist, Blank) · system prompt with `{{variables}}` · first message · knowledge base (paste or upload) · voice, speed, language, model, temperature · max call length |
| **Test instantly** | **Chat** playground (only needs an OpenAI key) · **Voice** call in the browser via your mic · **Phone** — the agent calls your mobile |
| **Actions** | Appointment booking (Cal.com or realistic mock slots) · warm transfer to a human · `end_call` with outcomes |
| **Campaigns** | CSV import (extra columns become prompt variables) · pick an agent · concurrency limit · start / pause / resume · call selected contacts |
| **Call logs** | Full transcript with tool calls · AI summary · outcome · sentiment · your custom extracted fields · re-analyze |
| **Dashboard** | Calls, talk time, meetings booked, success rate, calls per day, outcome breakdown, setup checklist |

## Quickstart — test in ~5 minutes

You need Python 3.11+ and Node 20+.

```bash
# 1) API  (SQLite by default — no database to set up)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # put at least OPENAI_API_KEY in it
uvicorn main:app --reload --port 8000

# 2) Web app  (new terminal)
cd web
npm install
npm run dev                   # → http://localhost:3000
```

Open **http://localhost:3000 → Agents → Outbound Sales SDR → Chat** and start talking to it.
That's the whole loop with just an OpenAI key.

### Unlock voice in the browser

Add these to `backend/.env`, restart the API, and start the voice worker:

| Key | Where |
|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Free project at [cloud.livekit.io](https://cloud.livekit.io) → Settings → Keys |
| `DEEPGRAM_API_KEY` | [console.deepgram.com](https://console.deepgram.com) (free credit) |
| `CARTESIA_API_KEY` | [play.cartesia.ai/keys](https://play.cartesia.ai/keys) — also unlocks the full voice picker |

```bash
cd backend
python agent_worker.py download-files   # first time only (VAD + turn-detector models)
python agent_worker.py dev              # keep running alongside the API
```

Now the **Voice** tab in the agent editor puts you on a live call with your agent.

### Unlock real phone calls + campaigns

Create a LiveKit **outbound SIP trunk** (e.g. Twilio Elastic SIP Trunking → LiveKit —
[guide](https://docs.livekit.io/sip/quickstarts/configuring-twilio-trunk/)) and set
`LIVEKIT_SIP_OUTBOUND_TRUNK_ID`. The **Phone** tab and campaigns start dialing.

Optional: `CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID` for real calendar bookings.

The app's **Settings** page shows which of these are connected at any time.

### Or: Docker

```bash
cp backend/.env.example backend/.env   # add keys
docker compose up --build              # API :8000 · worker · web :3000
```

### Deploy to Render (gets you a URL) — free tier

`render.yaml` deploys the whole app as **one free web service** (web UI + API + voice worker in a
single container, see the root `Dockerfile`) plus a free Postgres database:

1. [render.com](https://dashboard.render.com) → **New → Blueprint** → pick this repo and branch.
2. Paste your keys when prompted (OpenAI, LiveKit, Deepgram, Cartesia) and an `AUTH_EMAIL` /
   `AUTH_PASSWORD` for the site login → **Apply**.
3. Open the `closer` service's URL (`https://closer-….onrender.com`).

Free instances sleep after ~15 idle minutes and take about a minute to wake on the next visit; the
voice worker sleeps with them. It runs in a low-memory mode (calls run as threads, VAD-only turn
detection) to fit 512 MB. For always-on calling and campaigns, upgrade the instance and set
`LOW_RESOURCE_MODE=false`, or run the services separately with `docker-compose.yml`.

### Before putting it on the internet

- Set `AUTH_PASSWORD` (and `AUTH_EMAIL`, `AUTH_SECRET`) for the web app — the login screen is off when it's empty.
- Keep the API private (only the web app and worker need to reach it); it has no auth of its own.
- Use Postgres: `DATABASE_URL=postgresql+asyncpg://…` (tables/columns are created on startup).
- Set `WEBHOOK_BASE_URL` to an address the worker can reach the API on.

## How it works

```
 Browser ──► web (Next.js) ──/api proxy──► API (FastAPI) ──► DB (SQLite/Postgres)
    │                                        │   ▲
    │ WebRTC (voice test)                     │   │ outcome + transcript webhook
    ▼                                        ▼   │
 LiveKit room ◄── dispatch(agent config) ── API  │
    │  ▲                                          │
    │  └── SIP outbound (phone/campaign calls)    │
    ▼                                             │
 Voice worker: Deepgram STT → OpenAI LLM (+tools) → Cartesia TTS ──┘
                                     post-call: OpenAI summary / outcome / extraction
```

1. Every call (browser test, phone test, campaign) creates a LiveKit room whose metadata carries the
   agent's config and the contact's variables.
2. The worker (`agent_worker.py`) builds the agent from that config: prompt + knowledge base, voice,
   model and only the tools that agent has enabled.
3. When the call ends the worker posts the transcript + outcome; the API runs post-call analysis and the
   result shows up in Call Logs.

## Repository layout

```
backend/
  main.py                    FastAPI app
  agent_worker.py            LiveKit voice worker (configurable agents + original Paul SDR)
  app/agent/templates.py     Starter agent templates
  app/agent/runtime.py       Prompt assembly shared by chat + voice
  app/routers/agents.py      Agent CRUD, chat playground, web/phone test calls
  app/routers/campaigns.py   Campaigns, CSV import, dialer queue with concurrency
  app/routers/calls.py       Call logs + dashboard overview
  app/routers/settings.py    Integration status + Cartesia voice catalog
  app/services/              Calls (LiveKit), LLM (playground + analysis), calendar (Cal.com)
  tests/                     pytest suite  (pytest -q tests)
web/                         The platform UI (Next.js 15, Tailwind 4, livekit-client)
frontend/                    Original Pounce UI — needs a private @hemut2025 package, kept for reference
research/                    Voice-agent research notes from the original project
```

---

*The sections below are from the original Pounce project and describe the research behind the voice pipeline.*

## The research behind it

Most voice agents fail on the phone because they're built the same way as text chatbots — no understanding of how real-time spoken conversation actually works. Before writing a line of agent code, we went through recent academic literature on voice AI and extracted what actually moves the needle.

Five papers shaped the design:

### [ConvFill — Conversational Fillers for Real-Time Voice Agents](https://arxiv.org/abs/2511.07397)
**What it says:** When a voice agent needs to call an external tool (calendar, CRM, API), there's an unavoidable latency gap. Without intervention, the prospect hears dead silence and assumes the call dropped. ConvFill shows that injecting a hard-coded natural filler _before_ the tool call — not generated by the LLM, just a fixed phrase — eliminates the perceived pause with near-zero latency overhead.

**What we built:** `_say_filler()` in `agent_worker.py` — a method that bypasses the LLM entirely and fires text straight to Cartesia TTS before every Cal.com slot fetch and booking API call. "One sec, let me check what's open around then…" starts playing within milliseconds. The API call runs in parallel.

---

### [LTS-VoiceAgent — Latency-Tolerant Streaming Voice Agents](https://arxiv.org/abs/2601.19952)
**What it says:** End-of-turn detection (endpointing) is a fixed silence threshold in most systems. That threshold is a major source of both false positives (cutting the prospect off mid-sentence) and false negatives (long pauses after complex input like spelling an email address). LTS-VoiceAgent proposes state-aware endpointing — the silence window should adapt based on what kind of input the agent is waiting for.

**What we built:** A `_dictation_mode` flag on the agent. When Paul has just offered meeting slots and is waiting for the prospect to spell their email, a `stt_node` override extends Deepgram's endpointing from 400ms to 1200ms. The window snaps back to normal after the booking is confirmed.

---

### [τ-Voice — Turn-Taking and Backchannel Modeling for Voice Agents](https://arxiv.org/abs/2603.13686)
**What it says:** Human speech is full of backchannels — brief acknowledgments like "yeah", "right", "go ahead", "mhm" that signal continued attention without yielding the floor. Most voice systems treat these as real interruptions, which causes the agent to stop speaking and generate a confused response to a one-word non-question. τ-Voice categorises these and shows that suppressing barge-in for known backchannels dramatically reduces unhelpful interruptions.

**What we built:** A 30-entry `_BACKCHANNELS` frozenset in `agent_worker.py`. When `conversation_item_added` fires with a user message that matches the list, Paul's response is overridden with a "continue naturally" instruction via `session.generate_reply()` — the LLM never sees the backchannel as a new topic.

---

### [Speculative Interaction Agents](https://arxiv.org/abs/2605.13360)
**What it says:** The standard pipeline — wait for user to finish → STT → LLM → TTS → speak — has irreducible latency because each stage blocks the next. Speculative interaction proposes running the LLM speculatively during the user's utterance, not after. For tool-heavy agents the gains are most visible when the LLM can predict which tool it will call before the full utterance lands.

**What we built:** `preemptive_generation: {"enabled": False}` in the current build (deliberately off). The paper's approach requires careful rollback logic when speculation is wrong, which introduces its own failure modes. We documented it for future implementation once the qualification flow is stable enough to predict tool calls reliably.

---

### [VeriGuard — Hallucination Detection for Tool-Calling Voice Agents](https://arxiv.org/abs/2510.05156)
**What it says:** When a voice LLM calls a tool (e.g., a booking API), it sometimes generates plausible-sounding but fabricated parameters — an invented meeting time, a mangled email address — because the LLM is optimising for fluent speech, not data fidelity. VeriGuard proposes a lightweight verification pass on tool arguments before execution.

**What we built:** Gate-protected tool calls in `agent_worker.py`. `book_meeting` and `confirm_meeting` both validate pre-conditions via `state.can_book_meeting()` before touching the Cal.com API. Meeting times are never invented — the agent may only offer slots that the Cal.com API actually returned, stored in `state._available_slots`. Email addresses are validated for `@` presence before a booking is created.

---

The full research survey (15 papers reviewed, 5 implemented, notes on what was skipped and why) is in [`research/`](research/).

## Contributing

PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

Good places to start: new CRM integrations (HubSpot, Salesforce), additional TTS voices, language support, campaign analytics.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

[LiveKit](https://livekit.io/) · [Deepgram](https://deepgram.com/) · [Cartesia](https://cartesia.ai/) · [OpenAI](https://openai.com/) · [Cal.com](https://cal.com/) · [Orange Slice.AI](https://orangeslice.ai)

Research: ConvFill ([arXiv:2511.07397](https://arxiv.org/abs/2511.07397)) · LTS-VoiceAgent ([arXiv:2601.19952](https://arxiv.org/abs/2601.19952)) · τ-Voice ([arXiv:2603.13686](https://arxiv.org/abs/2603.13686)) · Speculative Interaction Agents ([arXiv:2605.13360](https://arxiv.org/abs/2605.13360)) · VeriGuard ([arXiv:2510.05156](https://arxiv.org/abs/2510.05156))
