"""
Starter help-center articles, written from what the app actually does today (screens, buttons and
prices in this codebase). Added once, only when the help center is empty; admins edit them freely.
"""

from __future__ import annotations

from sqlalchemy import func, select
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
        "summary": "About 1 credit per connected minute on Standard models; plan credits renew monthly, bought credits never expire.",
        "body": """Calls use calling credits for connected time. On Standard models a credit is about one minute of calling; Premium models use a little more per minute. You can see the rate for each agent in the agent editor. Phone calls also include a small phone-line fee per started minute. Calls that don't connect don't use credits.

Plans include credits every month (Solo 150, Growth 400, Teams 900, Managed 1,500). Plan credits are added each paid billing period and expire at the end of it. Credits you buy separately never expire and are used after your plan credits.

If credits run out, campaigns pause until you add more.""",
    },
    {
        "slug": "buy-more-credits", "category": "credits_billing", "title": "Buy more credits and auto-recharge",
        "summary": "Billing & Usage → Calling Credits: packs of 75 ($29), 500 ($139) or 1,000 ($260), and optional auto-recharge.",
        "body": """Go to Billing & Usage → Calling Credits and choose a pack: 75 credits for $29, 500 for $139, or 1,000 for $260. Payment is through secure Stripe checkout and the credits are added once the payment is confirmed. Bought credits never expire.

You can also turn on auto-recharge, which buys a pack you choose when your balance drops below a threshold, with a monthly spending cap. It's off until an account owner or admin turns it on and confirms.""",
    },
    {
        "slug": "plans-overview", "category": "credits_billing", "title": "Plans",
        "summary": "Solo $98, Growth $197, Teams $349 per month; Managed starts at $797 and is set up with our team.",
        "body": """Solo — $98/month: 150 credits, 2 agents, 1 user, 1 phone number.
Growth — $197/month: 400 credits, 4 agents, 4 users, 2 numbers, 1 CRM integration, workflow automations, Radar.
Teams — $349/month: 900 credits, 8 agents, 10 users, 4 numbers, multiple CRMs, webhooks and the API, member roles, team analytics.
Managed — starting at $797/month: 1,500 credits, 12 agents, 15 users and hands-on setup by our team. Book a call with sales from the Plans page.

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


async def seed(db: AsyncSession) -> int:
    if (await db.execute(select(func.count()).select_from(KbArticle))).scalar_one():
        return 0
    for a in ARTICLES:
        db.add(KbArticle(published=True, **a))
    await db.commit()
    return len(ARTICLES)
