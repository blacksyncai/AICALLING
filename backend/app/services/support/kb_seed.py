"""
Help-center articles, written from what the app actually does today (screens, buttons and prices in
this codebase). The support AI answers only from published articles. Missing articles are added on
startup; admins edit them freely (edited articles are never overwritten).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support import KbArticle

ARTICLES: list[dict] = [
    {
        "slug": "create-an-ai-calling-agent", "category": "agent_builder", "title": "Create an AI calling agent",
        "summary": "Three ways to make an agent: Build with AI, build from scratch, or have an expert build it.",
        "body": """Go to Agents and choose New agent. You'll see three options:

1. Build with AI — answer a few questions about your business (or share your website) and BlackSync writes the agent's script, voice settings and knowledge for you. You review it, test it, then launch it.
2. Build from scratch — start from a blank agent and write the prompt, first message and settings yourself.
3. Have an expert build it — book a call with the BlackSync team and we build and test the agent with you.

Agents built with AI start paused. Press Launch when you're happy with it; until then you can still test it.""",
    },
    {
        "slug": "train-and-test-your-agent", "category": "agent_builder", "title": "Train and test your agent",
        "summary": "Edit the prompt, add knowledge, pick a voice and model, and test by chat, browser call or phone.",
        "body": """Open the agent from Agents to edit it:

- Prompt and first message: what the agent says and how it behaves on the call.
- Knowledge: facts the agent can use (services, pricing you want it to quote, FAQs). You can also manage shared knowledge under Knowledge in the sidebar.
- Voice and model: pick a voice (Standard or Premium voices) and the AI model. The model affects the credits used per minute.
- Calling settings: booking, call transfers and what to do on voicemail.

Test before you launch: use the chat playground, a browser call, or have the agent call your own phone. Every saved change keeps a version you can restore.""",
    },
    {
        "slug": "upload-contacts-csv", "category": "outbound_campaigns", "title": "Upload contacts from a CSV",
        "summary": "Import a CSV into a campaign by dropping the file, choosing it, or pasting it.",
        "body": """Open a campaign and press Import CSV. Drop a .csv file onto the box, choose a file, or paste the rows.

Your file needs a header row with at least name and phone. Optional columns include company, email and city. Example:

name,phone,company,email,city
Jane Cooper,+14155550123,Acme Inc,jane@acme.com,San Francisco

Phone numbers work best in international format (+1 for US numbers). You can also add a single contact with Add.""",
    },
    {
        "slug": "start-an-outbound-campaign", "category": "outbound_campaigns", "title": "Start an outbound campaign",
        "summary": "Create a campaign, pick an agent, add contacts, set calling rules and press Start campaign.",
        "body": """1. Go to Campaigns and create a new Outbound campaign.
2. Pick the agent that will make the calls.
3. Add contacts (Import CSV or Add).
4. Check the Calling rules: calling hours, days and time zone, and how many times to retry people who don't answer.
5. Press Start campaign.

You can pause and resume at any time. A campaign pauses on its own if your calling credits run out — add credits, then press Resume and it continues where it left off.""",
    },
    {
        "slug": "inbound-calls-and-forwarding", "category": "phone_numbers", "title": "Answer inbound calls with an agent",
        "summary": "Create an inbound campaign on one of your numbers, then forward your existing line to it.",
        "body": """To have an agent answer calls, create an Inbound campaign under Campaigns and pick one of your own BlackSync phone numbers and the agent that answers. Inbound campaigns go live when they're created.

To keep your existing business number, forward it to your BlackSync number. The inbound campaign page has a forwarding guide with the dial codes for Verizon, AT&T, T-Mobile, most business landlines, and steps for RingCentral, Google Voice and Dialpad — for every call or only the calls you miss.""",
    },
    {
        "slug": "phone-numbers", "category": "phone_numbers", "title": "Get a phone number",
        "summary": "Search by area code under Phone Numbers. Plans include numbers; extra numbers are $3.50/month.",
        "body": """Go to Phone Numbers, search by area code and add a number.

Plans include phone numbers (Solo 1, Growth 2, Teams 4, Managed 4). Each number beyond that is $3.50 per month. Without a plan you can still buy a number on its own for $3.50 per month through secure Stripe checkout; it's added once the payment goes through.""",
    },
    {
        "slug": "call-transfers", "category": "call_transfers", "title": "Set up call transfers",
        "summary": "Turn on Transfer to a person in the agent's settings and enter the number to transfer to.",
        "body": """Open the agent and turn on Transfer to a person, then enter the number to transfer to and describe when the agent should transfer (for example, when a caller is ready to book or asks for a person).

Test it by having the agent call your phone and asking to speak to someone. Make sure the transfer number can answer during your calling hours.""",
    },
    {
        "slug": "call-recordings-and-transcripts", "category": "getting_started", "title": "Find call recordings and transcripts",
        "summary": "Open Call Logs and select a call to see the recording, transcript and AI summary.",
        "body": """Go to Call Logs in the sidebar and open any call. The call page shows the recording (when recording is on for the agent), the full transcript, an AI summary, the outcome and anything the agent captured.

Recording is controlled per agent in the agent's settings.""",
    },
    {
        "slug": "how-calling-credits-work", "category": "credits_billing", "title": "How calling credits work",
        "summary": "0.8–1.3 credits per connected minute depending on the AI model, plus 0.053 per minute for the phone line.",
        "body": """Calls use calling credits for connected talk time, charged per second at the agent's rate. Every AI model has its own rate, from 0.8 credits a minute for the lightest model up to 1.3 for the most capable — the agent editor shows the exact rate under the LLM model picker. Fractions of a credit carry over to the next call, so you never pay for a rounded-up minute of AI time.

Phone calls also have a phone-line fee of 0.053 credits per started minute. Voicemails and calls shorter than 10 seconds only pay the phone-line fee, not AI time. Calls that never connect (no answer, busy, failed) cost nothing. Browser test calls have no phone-line fee, and new accounts get free test minutes for them.

Plans include credits every month (Solo 150, Growth 400, Teams 900, Managed 1,500). Plan credits are added each paid billing period and expire at the end of it. Credits you buy separately never expire and are used after your plan credits.

If credits run out, campaigns pause until you add more.""",
    },
    {
        "slug": "buy-more-credits", "category": "credits_billing", "title": "Buy more credits and auto-recharge",
        "summary": "Packs of 75 ($29), 500 ($139) or 1,000 ($260). One pack before you pick a plan; plans can buy any time and use auto-recharge.",
        "body": """Go to Billing & Usage → Calling Credits and choose a pack: 75 credits for $29, 500 for $139, or 1,000 for $260. Payment is through secure Stripe checkout and the credits are added once the payment is confirmed. Bought credits never expire.

Before you're on a plan, you can buy one credit pack. After that, choose a BlackSync AI plan to keep buying credits — on a plan you can buy packs any time.

Auto-recharge (plans only) buys a pack you choose whenever your balance drops below a threshold, with a monthly spending cap. It's off until an account owner or admin turns it on and confirms, and it uses the card saved from your first purchase.""",
    },
    {
        "slug": "plans-overview", "category": "credits_billing", "title": "Plans",
        "summary": "Solo $98, Growth $197, Teams $349 per month; Managed is custom-priced and set up with our team.",
        "body": """Solo — $98/month: 150 credits, 2 agents, 1 user, 1 phone number.
Growth — $197/month: 400 credits, 4 agents, 4 users, 2 numbers, 1 CRM integration, workflow automations, Radar.
Teams — $349/month: 900 credits, 8 agents, 10 users, 4 numbers, multiple CRMs, webhooks and the API, member roles, team analytics.
Managed — custom pricing: done-for-you setup, broker and multi-office rollouts, white-label options and ongoing optimization by our team (12 agents, 15 users). Pricing is tailored to your business — book a call with sales from the Plans page.

Extra agent slots are $19/month each. See Billing & Usage → Plans for the full comparison and to change plans.""",
    },
    {
        "slug": "connect-your-crm", "category": "crm_integrations", "title": "Connect your CRM",
        "summary": "Integrations → pick your CRM → Connect. Calls are logged back automatically.",
        "body": """Go to Integrations and choose your CRM — Follow Up Boss, Close, HubSpot, GoHighLevel, Pipedrive and Attio are supported, plus Slack notifications. Press Connect and either sign in or paste your API key.

Once connected, open the integration's setup page to choose what's sent back after calls (summaries, outcomes, which calls), import contacts to call, set up automatic imports, and optionally create an AI calling pipeline in the CRM. CRM integrations are included from the Growth plan.""",
    },
    {
        "slug": "invite-team-members", "category": "account_settings", "title": "Invite team members",
        "summary": "Open Account → Team and invite by email. The number of users depends on your plan.",
        "body": """Open your Account (from the menu at the bottom of the sidebar) and go to the Team tab. Enter the person's email and choose their role, then send the invite. If email isn't set up, you'll get a link to share with them.

Pending invites count toward your plan's user limit (Solo 1, Growth 4, Teams 10, Managed 15). Admin roles are included from the Teams plan.""",
    },
    {
        "slug": "campaign-not-calling", "category": "troubleshooting", "title": "My campaign isn't calling",
        "summary": "Check credits, the campaign status, calling hours and the agent.",
        "body": """If a campaign isn't placing calls, check:

1. Calling credits — campaigns pause when credits run out (Billing & Usage).
2. Status — the campaign must be running. Paused campaigns show why at the top of the campaign page.
3. Calling hours — calls only go out inside the campaign's calling hours, days and time zone.
4. Contacts — there must be contacts left to call (not already called the maximum number of times or marked do-not-call).
5. Agent — the campaign needs an active agent, and your plan's active-agent limit applies.

If it still isn't calling, contact support from this chat and include the campaign name.""",
    },
]


# Added after launch. New slugs are added to existing help centers; see seed().
ARTICLES += [
    {
        "slug": "ai-models-explained", "category": "agent_builder", "title": "Which AI model should my agent use?",
        "summary": "The model is the agent's brain. Faster, smarter models cost a little more per minute.",
        "body": """The AI model is the agent's "brain": it decides what to say next on the call. Pick it in the agent editor under Voice & Model → LLM model. Each model shows its credit rate per minute, and models with a crown are premium (above 1 credit a minute).

BlackSync models:
- BlackSync Super Intelligence · Ultra (1.2 credits/min) — our flagship. Runs on wafer-scale supercomputer chips in dedicated, liquid-cooled AI data centers, so it reads and writes thousands of tokens a second. Best for complex scripts, objections and booking.
- BlackSync Super Intelligence · Flash (1.1/min) — the same data-center hardware, tuned for speed on short, high-volume calls.
- BlackSync Flash Pro (1.1/min) — handles long scripts, objections and tools well.
- BlackSync Flash Plus (1.0/min) and Flash 2.1 (1.0/min) — smarter Flash models that follow longer scripts, still fast.
- BlackSync Flash (0.9/min) — quick, natural replies and reliable call tools at low cost. A great default.
- BlackSync Flash Lite (0.8/min) — the lightest and cheapest; best for very simple, high-volume scripts.

Other models are also available, including GPT-4.1 (1.1/min), GPT-4.1 mini (0.9/min), GPT-4.1 nano (1.0/min), GPT-4o (1.2/min), GPT-4o mini (1.0/min), Claude Haiku 5.5 (0.9/min) and Claude Sonnet 5.5 (1.3/min).

How to choose: start with BlackSync Flash or Super Intelligence · Ultra, run a few test calls, and move up only if the agent misses instructions. Rates shown here are the defaults — the agent editor always shows your account's exact rate.""",
    },
    {
        "slug": "why-some-models-cost-more", "category": "credits_billing", "title": "Why do some AI models cost more?",
        "summary": "Bigger, faster models need more computing power per call, so they use a few more credits per minute.",
        "body": """Every minute of a call, the AI model re-reads the whole conversation and your agent's instructions to decide what to say next — often several times a minute. Larger, smarter models do much more computing for each reply, and the fastest ones run on specialised hardware, so they cost more to run.

That's why rates range from 0.8 credits a minute (BlackSync Flash Lite) to 1.3 (Claude Sonnet 5.5). Premium models (above 1 credit a minute) are marked with a crown in the model picker.

The difference per call is small: on a 3-minute call, moving from a 0.9 model to a 1.2 model uses about 0.9 more credits. Pick the cheapest model that handles your script well — for most outreach, BlackSync Flash or Super Intelligence · Ultra is plenty. You can change the model any time in the agent editor, and the new rate applies to the next call.""",
    },
    {
        "slug": "latency-and-response-speed", "category": "agent_builder", "title": "How fast does the agent respond? (latency)",
        "summary": "Agents reply in about a second. BlackSync Super Intelligence runs on data-center supercomputer chips for near-instant answers.",
        "body": """Response time ("latency") is how long the agent pauses after the caller stops talking. BlackSync agents typically start answering in about a second, which sounds natural on the phone.

What affects it:
- The AI model. BlackSync Super Intelligence runs on wafer-scale supercomputer chips in dedicated, liquid-cooled AI data centers, processing thousands of tokens a second — so the reply is written almost instantly. BlackSync Flash models are also built for quick replies.
- Responsiveness setting. In Voice & Model → Voice tuning, higher Responsiveness answers sooner after the caller stops talking; lower waits a little longer so it doesn't cut people off.
- The script. Very long prompts and knowledge make every reply a little slower. Keep instructions focused.
- The phone line. Mobile reception on the caller's side can add a short delay.

The agent also starts preparing its answer while the caller is finishing their sentence, and writes its opening line while the phone is ringing, so it can speak as soon as someone picks up.

If an agent feels slow, try a BlackSync Super Intelligence or Flash model, raise Responsiveness a little, and trim the prompt.""",
    },
    {
        "slug": "voices-explained", "category": "agent_builder", "title": "Choose a voice for your agent",
        "summary": "Standard voices, Premium cloned voices, tones and versions, speed and voice tuning.",
        "body": """Pick the agent's voice in the agent editor under Voice & Model → Voice. Press play on any voice to hear a preview.

- Standard voices — professional, natural-sounding voices for any business.
- Premium voices — lifelike cloned voices.
- Tones and versions — some voices come in several tones (for example Neutral, Confident, Cheerful, Excited) or versions. Click a tone to switch, and press play to hear it before you save.

You can also adjust:
- Speaking speed — slower or faster speech.
- Volume — how loud the agent speaks.
- Responsiveness — how soon it answers after the caller stops talking.
- Interruption sensitivity — how easily the caller can cut in.
- Pronunciation dictionary — spell a word the way it should be said (for example a brand or a name).

The voice works with any AI model. Test with a phone call to hear exactly what your leads will hear.""",
    },
    {
        "slug": "languages", "category": "agent_builder", "title": "Which languages can my agent speak?",
        "summary": "English, Spanish, French, German, Portuguese, Italian, Dutch, Hindi, Japanese, or Multilingual (auto).",
        "body": """Set the agent's language in Voice & Model → Language. Supported languages: English, Spanish, French, German, Portuguese, Italian, Dutch, Hindi and Japanese.

Multilingual (auto) lets the agent understand and switch between languages on the same call.

Pick a voice that speaks the same language — the editor warns you if the voice and the agent's language don't match. Write the agent's instructions in the language you want it to speak, or tell it explicitly which language to use.""",
    },
    {
        "slug": "write-a-great-prompt", "category": "agent_builder", "title": "Write a great agent prompt",
        "summary": "Tell the agent who it is, the goal of the call, the steps to follow and how to handle objections.",
        "body": """The prompt is the agent's instructions. Good prompts are short and specific:

1. Who it is — name, company and role ("You're Sarah from Summit Realty").
2. The goal — one clear outcome ("book a 15-minute call with an agent").
3. The steps — open, qualify with 2–3 questions, offer times, confirm.
4. Objections — how to answer the 3–5 most common ones.
5. Rules — what never to say, when to end the call politely.

Put facts (services, prices, hours, FAQs) in Knowledge instead of the prompt, so every agent stays consistent. Use variables like {{name}} and {{company}} to personalise calls from your contact list.

Leave the first message empty to let the agent write a natural opening for each contact, or write one to control the exact opening line. Test, listen to the recording, adjust, repeat.""",
    },
    {
        "slug": "business-knowledge", "category": "agent_builder", "title": "Add business knowledge",
        "summary": "Knowledge holds the facts every agent can use: services, hours, pricing, FAQs.",
        "body": """Go to Knowledge in the sidebar to add your business information: services, hours, locations, pricing you're happy to quote, policies and common questions. Every agent can use it to answer callers accurately.

You can also add knowledge to a single agent from its Knowledge tab in the agent editor.

Tips: keep it factual and up to date, write answers the way you'd say them on the phone, and remove anything you don't want an agent to tell callers. If an agent gets a fact wrong, fix it here — it's used on the very next call.""",
    },
    {
        "slug": "book-meetings-on-calls", "category": "agent_builder", "title": "Let your agent book meetings",
        "summary": "Turn on booking, connect Cal.com and set the calendar's time zone.",
        "body": """Agents can check your real availability and book meetings during the call.

1. Open the agent → Actions → Calendar booking and turn it on.
2. Add your Cal.com API key and the event type ID to book into.
3. Set the Time zone — slots are offered and booked in this zone. Make sure your Cal.com account and availability schedule use the same time zone.

On the call, the agent offers open times, confirms the contact's email (spelled out) and books it. Booked meetings appear under Meetings with the time, contact and a call summary. You can also connect Google Calendar on the Meetings page to see them alongside your events.

If booking isn't connected, the agent can still agree a time and the team gets the details in the call log.""",
    },
    {
        "slug": "voicemail-handling", "category": "outbound_campaigns", "title": "What happens when a call goes to voicemail?",
        "summary": "Choose to hang up or leave a message. Voicemails only cost the phone-line fee.",
        "body": """BlackSync detects answering machines in the first seconds of an outbound call. In the agent's Actions you choose what happens:

- Hang up — end the call and try again later (if the campaign retries).
- Leave a message — wait for the beep and leave the message you write.

Voicemails don't use AI credits — only the small phone-line fee for the call time.""",
    },
    {
        "slug": "calling-hours-and-retries", "category": "outbound_campaigns", "title": "Calling hours, retries and how many calls at once",
        "summary": "Each campaign has calling hours, days, a time zone, retry rules and a concurrency limit.",
        "body": """In a campaign's Calling rules you set:

- Calling hours and days — calls only go out inside this window.
- Time zone — the window is in this zone (use your contacts' time zone).
- Retries — how many times to try someone who doesn't answer, and how long to wait between attempts.

How many calls run at the same time depends on your plan: Solo 2, Growth 3, Teams 5, Managed 8.

Respect local calling-time rules for the people you call. Contacts marked do-not-call are never dialed.""",
    },
    {
        "slug": "test-your-agent", "category": "getting_started", "title": "Test your agent before launch",
        "summary": "Chat, browser call or have the agent call your phone from the Test your agent panel.",
        "body": """In the agent editor, the Test your agent panel has three ways to test:

- Voice — talk to the agent in your browser (use headphones).
- Chat — type to it to check the script quickly.
- Phone — enter your number and the agent calls you right now. If your account has phone numbers, choose which one it calls from.

Set a test contact (name, company) to see how personalisation sounds. After each test, open Call Logs to review the transcript and recording, adjust the prompt, and test again. The launch checklist at the top of the editor shows anything still missing before you launch.""",
    },
    {
        "slug": "call-outcomes-and-analysis", "category": "getting_started", "title": "Call outcomes, summaries and post-call analysis",
        "summary": "Every call gets an outcome, a summary, sentiment and the fields you ask the AI to capture.",
        "body": """After each call, BlackSync analyses the conversation and adds to the call log:
- An outcome (for example meeting booked, not interested, voicemail, no answer, do not call).
- A short summary and the caller's sentiment.
- Any details you asked for in the agent's Post-call analysis tab (for example budget, timeline, property address), plus your success criteria.

Find everything under Call Logs. Analytics shows trends across calls — where calls drop off, which agents and campaigns book the most meetings, and the best hours to call. If your CRM is connected, outcomes and summaries can be sent back automatically.""",
    },
    {
        "slug": "free-trial", "category": "getting_started", "title": "Getting started with your new account",
        "summary": "New accounts start with calling credits and a welcome agent. Buy one credit pack before choosing a plan; plans unlock more.",
        "body": """New accounts start with calling credits and a ready-to-test welcome agent, so you can hear BlackSync on a real call in minutes.

Right away you can build and test agents, run campaigns with your starting credits, and buy one credit pack if you need more minutes. To keep buying credits, turn on auto-recharge and get monthly included credits, numbers and more agents and users, choose a plan under Billing & Usage → Plans.

Want help setting up? Book a free walkthrough from the Plans page or ask here.""",
    },
    {
        "slug": "change-or-cancel-plan", "category": "credits_billing", "title": "Change or cancel your plan",
        "summary": "Billing & Usage → Plans to upgrade or downgrade; cancel any time and keep access until the period ends.",
        "body": """Go to Billing & Usage → Plans. You'll see a preview of the price change before you confirm an upgrade or downgrade.

To cancel, press Cancel plan on the Plans tab. You keep your plan until the end of the period you've paid for, and you can press Keep my plan any time before then to stay. Manage in Stripe lets you update your card and download receipts. Credits you bought separately never expire, even after cancelling.

Invoices and payment methods are under Billing & Usage → Invoices.""",
    },
    {
        "slug": "phone-line-fee", "category": "credits_billing", "title": "What is the phone-line fee?",
        "summary": "0.053 credits per started minute on phone calls, on top of the AI model's rate.",
        "body": """Phone calls use the phone network, which has its own cost. BlackSync charges a phone-line fee of 0.053 credits per started minute on phone calls (inbound and outbound), on top of the agent's AI rate.

Example: a 2-minute call on a 0.9 credits/minute model uses 1.8 + 2 × 0.053 = about 1.91 credits.

Browser test calls don't have a phone-line fee. Calls that never connect cost nothing, and voicemails or calls under 10 seconds only pay the phone-line fee.""",
    },
    {
        "slug": "caller-id-and-pickup-rates", "category": "phone_numbers", "title": "Caller ID and getting more pickups",
        "summary": "Use your own local number, choose it per agent, and keep calls relevant.",
        "body": """Until you add a number, calls go out from the shared BlackSync line. A number of your own:
- gets more pickups (people answer local numbers more),
- keeps your caller reputation separate from other accounts,
- lets contacts call you back — pair it with an inbound campaign so an agent answers.

Choose which number an agent calls from in the agent's Actions → Call from, or set an account default under Phone Numbers.

To protect pickup rates: call people who expect to hear from you, stay inside reasonable calling hours, don't redial the same person too often, and honor do-not-call requests right away.""",
    },
    {
        "slug": "speed-to-lead", "category": "crm_integrations", "title": "Call new leads instantly (speed to lead)",
        "summary": "Connected CRMs can send new leads straight to an agent, called within about a minute.",
        "body": """When your CRM is connected, BlackSync can call new leads automatically as soon as they land — the faster you call, the more likely they answer.

Open the CRM's page under Integrations and, under Speed to lead, choose the agent that should call them. New leads are called within about a minute, between 8 AM and 9 PM in your account's time zone; leads that arrive later are called when the window opens. It's off until you pick an agent, uses calling credits, and do-not-call contacts are never dialed. (Available for CRMs that support it.)""",
    },
    {
        "slug": "radar", "category": "crm_integrations", "title": "What is Radar?",
        "summary": "Radar scans your CRM for the people worth calling right now and hands them to an agent.",
        "body": """Radar reads your connected CRM (Close or Follow Up Boss) — leads, deals, calls, emails, texts and website visits — and finds who to call now: hot leads, people who went quiet, new sign-ups and more. Send them to an agent in one tap.

Radar is included from the Growth plan. Without it you'll see an interactive preview on the Radar page.""",
    },
    {
        "slug": "lead-finder", "category": "getting_started", "title": "Lead Finder: look up property owners",
        "summary": "Search an address to find the owner's contact details. 5 free lookups a day, then paid lookups.",
        "body": """Lead Finder (for real-estate accounts) looks up the owner of a property from its address, with contact details when they're available, so you can add them to a campaign.

You get 5 free lookups every day. After that, lookups use your lookup balance — add funds under Billing & Usage → Lookups ($5, $10 or $25; bigger amounts give you more lookups per dollar). By default you're only charged when an owner is found.""",
    },
    {
        "slug": "plan-limits-explained", "category": "credits_billing", "title": "What do plan limits include?",
        "summary": "Agents, users, phone numbers, CRMs, calls at once and features by plan.",
        "body": """What each plan includes:

- Solo ($98/mo): 150 credits, 2 active agents, 1 user, 1 phone number, 2 calls at once.
- Growth ($197/mo): 400 credits, 4 agents, 4 users, 2 numbers, 1 CRM, 3 calls at once, workflows, Radar.
- Teams ($349/mo): 900 credits, 8 agents, 10 users, 4 numbers, unlimited CRMs, 5 calls at once, advanced workflows, roles, team reporting, Radar.
- Managed (custom pricing): tailored credit volume, 12 agents, 15 users, 4 numbers, unlimited CRMs, 8 calls at once, everything in Teams, set up with our team.

Extra agent slots are $19/month and extra phone numbers $3.50/month. Paused agents don't count toward the agent limit. See Billing & Usage → Plans to compare and switch.""",
    },
    {
        "slug": "team-roles", "category": "account_settings", "title": "Team roles and permissions",
        "summary": "Owners and admins manage billing and settings; members build and run agents and campaigns.",
        "body": """Each person on your account has a role:
- Owner — full access, including billing and deleting the account.
- Admin — manage billing, numbers, integrations and the team (admin roles are included from the Teams plan).
- Member — build and test agents, run campaigns and see results.

Invite people from Account → Team. The number of users depends on your plan (Solo 1, Growth 4, Teams 10, Managed 15).""",
    },
    {
        "slug": "data-privacy-and-security", "category": "account_settings", "title": "Is my data private and secure?",
        "summary": "Your data stays private to your workspace. Keys are encrypted and payments go through Stripe.",
        "body": """Your contacts, calls, recordings and settings are private to your workspace — other BlackSync accounts can't see them. API keys you add (for example your CRM or Cal.com) are stored encrypted. Payments are handled by Stripe; BlackSync never sees your full card number.

Call recordings are optional per agent. Some places require telling callers a call is recorded — add it to the agent's opening line if needed. Agents tell callers they're an AI assistant when asked (AI disclosure).""",
    },
    {
        "slug": "calling-compliance", "category": "outbound_campaigns", "title": "Calling rules and compliance",
        "summary": "Call people who expect to hear from you, respect calling hours and honor do-not-call requests.",
        "body": """You're responsible for following the calling laws where you and your contacts are (for example consent and do-not-call rules for AI and automated calls). Good practice:

- Call contacts who've given consent or expect to hear from you.
- Keep campaigns inside reasonable local calling hours.
- Honor opt-outs: when someone asks not to be called, the agent marks them do-not-call and they're never dialed again.
- Keep AI disclosure on, and mention recording if your location requires it.

This isn't legal advice — check with your counsel for your use case.""",
    },
    {
        "slug": "agent-sounds-off", "category": "troubleshooting", "title": "My agent sounds robotic, slow or talks over people",
        "summary": "Tune the voice, responsiveness and interruption sensitivity, or try another model or voice.",
        "body": """Quick fixes:

- Sounds robotic: try a different voice, or a Premium voice. Lower the speaking speed slightly. Use the pronunciation dictionary for names it says wrong.
- Too slow to answer: raise Responsiveness in Voice tuning, switch to a BlackSync Super Intelligence or Flash model, and shorten long prompts.
- Talks over people / cuts them off: lower Responsiveness a little so it waits for the caller to finish.
- Hard to interrupt: raise Interruption sensitivity.
- Says the wrong thing: tighten the prompt's steps and rules, and put facts in Knowledge.

Test by having the agent call your phone, then review the transcript in Call Logs.""",
    },
    {
        "slug": "contact-support", "category": "getting_started", "title": "Get help from the BlackSync team",
        "summary": "Chat with AI support any time, ask for a person, open a ticket or book a walkthrough.",
        "body": """Use the chat button in the corner of the app:
- Chat with AI support for instant answers any time.
- Tap Talk to a person — the team is notified and joins the chat. If no one is online, the AI keeps helping and the team follows up.
- Submit a support ticket for anything that needs a closer look; you'll get replies in the ticket.

Want us to set up your agent with you? Book a free walkthrough from Billing & Usage → Plans.""",
    },
]

# Earlier wording of articles we've since updated. A help center still showing one of these exact texts
# (never edited by an admin) gets the new version; edited articles are left alone.
_PREVIOUS_BODIES: dict[str, list[str]] = {
    'buy-more-credits': ["Go to Billing & Usage → Calling Credits and choose a pack: 75 credits for $29, 500 for $139, or 1,000 for $260. Payment is through secure Stripe checkout and the credits are added once the payment is confirmed. Bought credits never expire.\n\nOn the free trial (no plan yet) you can buy one credit pack. After that, choose a BlackSync AI plan to keep buying credits — on a plan you can buy packs any time.\n\nAuto-recharge (plans only) buys a pack you choose whenever your balance drops below a threshold, with a monthly spending cap. It's off until an account owner or admin turns it on and confirms, and it uses the card saved from your first purchase."],
    'free-trial': ['New accounts start with free trial calling credits and a ready-to-test welcome agent, so you can hear BlackSync on a real call in minutes.\n\nDuring the trial you can build and test agents, run campaigns with your trial credits, and buy one credit pack if you need more minutes. To keep buying credits, turn on auto-recharge and get monthly included credits, numbers and more agents and users, choose a plan under Billing & Usage → Plans.\n\nWant help setting up? Book a free walkthrough from the Plans page or ask here.'],
    'plans-overview': ['Solo — $98/month: 150 credits, 2 agents, 1 user, 1 phone number.\nGrowth — $197/month: 400 credits, 4 agents, 4 users, 2 numbers, 1 CRM integration, workflow automations, Radar.\nTeams — $349/month: 900 credits, 8 agents, 10 users, 4 numbers, multiple CRMs, webhooks and the API, member roles, team analytics.\nManaged — starting at $797/month: 1,500 credits, 12 agents, 15 users and hands-on setup by our team. Book a call with sales from the Plans page.\n\nExtra agent slots are $19/month each. See Billing & Usage → Plans for the full comparison and to change plans.'],
    'plan-limits-explained': ["What each plan includes:\n\n- Solo ($98/mo): 150 credits, 2 active agents, 1 user, 1 phone number, 2 calls at once.\n- Growth ($197/mo): 400 credits, 4 agents, 4 users, 2 numbers, 1 CRM, 3 calls at once, workflows, Radar.\n- Teams ($349/mo): 900 credits, 8 agents, 10 users, 4 numbers, unlimited CRMs, 5 calls at once, advanced workflows, roles, team reporting, Radar.\n- Managed (from $797/mo): 1,500 credits, 12 agents, 15 users, 4 numbers, unlimited CRMs, 8 calls at once, everything in Teams, set up with our team.\n\nExtra agent slots are $19/month and extra phone numbers $3.50/month. Paused agents don't count toward the agent limit. See Billing & Usage → Plans to compare and switch."],
    'how-calling-credits-work': ["Calls use calling credits for connected time. On Standard models a credit is about one minute of calling; Premium models use a little more per minute. You can see the rate for each agent in the agent editor. Phone calls also include a small phone-line fee per started minute. Calls that don't connect don't use credits.\n\nPlans include credits every month (Solo 150, Growth 400, Teams 900, Managed 1,500). Plan credits are added each paid billing period and expire at the end of it. Credits you buy separately never expire and are used after your plan credits.\n\nIf credits run out, campaigns pause until you add more."],
    'buy-more-credits': ["Go to Billing & Usage → Calling Credits and choose a pack: 75 credits for $29, 500 for $139, or 1,000 for $260. Payment is through secure Stripe checkout and the credits are added once the payment is confirmed. Bought credits never expire.\n\nYou can also turn on auto-recharge, which buys a pack you choose when your balance drops below a threshold, with a monthly spending cap. It's off until an account owner or admin turns it on and confirms."],
}


async def seed(db: AsyncSession) -> int:
    """Add articles the help center doesn't have yet (by slug) and refresh unedited copies of updated ones."""
    rows = {a.slug: a for a in (await db.execute(select(KbArticle))).scalars().all()}
    changed = 0
    for a in ARTICLES:
        row = rows.get(a["slug"])
        if row is None:
            db.add(KbArticle(published=True, **a))
            changed += 1
        elif row.body in _PREVIOUS_BODIES.get(a["slug"], []):
            row.body, row.summary, row.title = a["body"], a["summary"], a["title"]
            changed += 1
    if changed:
        await db.commit()
    return changed
