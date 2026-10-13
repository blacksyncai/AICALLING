"""
Application settings loaded from .env

Every provider key is optional so the API boots with zero configuration —
features light up as keys are added (see GET /api/settings/status):
  • OPENAI_API_KEY                         → chat playground + post-call analysis
  • LIVEKIT_* + DEEPGRAM + CARTESIA        → browser voice test calls
  • LIVEKIT_SIP_OUTBOUND_TRUNK_ID          → real phone calls / campaigns
"""

from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    # Any OpenAI-compatible endpoint works (Azure OpenAI, Groq, OpenRouter, a local proxy…).
    openai_base_url: str = "https://api.openai.com/v1"
    # Claude models for agents (Haiku/Sonnet); hidden from the model picker when unset.
    anthropic_api_key: str = ""
    # Cerebras (OpenAI-compatible): the "BlackSync Super Intelligence" models; hidden when unset.
    cerebras_api_key: str = ""
    # Mistral (OpenAI-compatible API) — the "BlackSync Flash" models.
    mistral_api_key: str = ""
    # Nango (OAuth for CRMs like Salesforce, HubSpot, Close); integrations configured in Nango show up in the app.
    nango_secret_key: str = ""
    # One-off repair jobs at startup (off in tests).
    run_startup_jobs: bool = True
    llm_model: str = "gpt-4.1-mini"
    # Model used for post-call summaries / data extraction.
    analysis_model: str = "gpt-4.1-mini"

    # ── Twilio ────────────────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # ── LiveKit ───────────────────────────────────────────────────────────────
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_outbound_trunk_id: str = ""
    livekit_sip_inbound_trunk_id: str = ""
    livekit_agent_name: str = "closer"

    # ── Phone numbers (Twilio, bought into the account behind the LiveKit trunk) ──
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    # Twilio Elastic SIP trunk the numbers attach to. Blank = found automatically by
    # matching the LiveKit outbound trunk's address (e.g. xyz.pstn.twilio.com).
    twilio_trunk_sid: str = ""

    # ── Call recordings (LiveKit egress → any S3-compatible bucket) ──
    recordings_s3_bucket: str = ""
    recordings_s3_endpoint: str = ""  # blank for AWS; e.g. https://storage.railway.app or an R2 endpoint
    recordings_s3_region: str = "auto"
    recordings_s3_access_key: str = ""
    recordings_s3_secret_key: str = ""
    recordings_s3_force_path_style: bool = False
    # Who records calls: "twilio" (trunk recording, copied into the bucket), "livekit" (egress) or "" = auto
    # (Twilio when its credentials are set — no LiveKit egress limits).
    recording_provider: str = ""
    # Small hosts (e.g. a 512 MB free instance): no pre-warmed job processes,
    # no turn-detector model (VAD-only end-of-turn), never report as "busy".
    low_resource_mode: bool = False

    # ── STT / TTS ─────────────────────────────────────────────────────────────
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""
    # Voice picker categories. Premium = the featured house voices + voices
    # owned/cloned in your Cartesia account + any ids listed here (comma-separated).
    voice_premium_label: str = "Premium Human Voices"
    voice_standard_label: str = "Standard AI Voices"
    premium_voice_ids: str = ""
    # Extra Cartesia voice ids for the Standard tab (comma-separated), beyond the house voices.
    standard_voice_ids: str = ""

    # ── Database ──────────────────────────────────────────────────────────────
    # Defaults to a local SQLite file so the app runs with no Postgres.
    database_url: str = "sqlite+aiosqlite:///./closer.db"
    secret_key: str = "dev-secret-change-me"

    # ── App ───────────────────────────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    sql_echo: bool = False

    # ── Demo ──────────────────────────────────────────────────────────────────
    demo_mode: bool = False
    demo_phone_number: str = ""

    # ── Cal.com ───────────────────────────────────────────────────────────────
    calcom_api_key: str = ""
    calcom_event_type_id: str = ""

    # ── Lead Finder (DataSkip property-owner lookups) ────────────────────────
    # Backend-only secret; never sent to the browser or logged.
    skiptrace_api_key: str = ""
    skiptrace_api_url: str = "https://app.dataskip.io"
    # Lookup results (contact details) are scrubbed after this many days.
    lead_finder_retention_days: int = 90

    # ── Billing (Stripe) ─────────────────────────────────────────────────────
    # Secret key (sk_live_… / sk_test_…) and webhook signing secret — backend only.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Fernet key that encrypts secrets pasted into the admin portal (e.g. the Stripe key).
    secrets_encryption_key: str = ""
    # Optional explicit price ids for plans (otherwise looked up by lookup key — see billing/catalog.py).
    stripe_price_solo: str = ""
    stripe_price_teams: str = ""
    # Included credits expire at the end of each billing cycle unless this is on.
    included_credits_rollover: bool = False

    # ── Orange Slice ──────────────────────────────────────────────────────────
    orange_slice_api_key: str = ""

    # ── Google Calendar (OAuth client from Google Cloud Console) ─────────────
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── Deployment ────────────────────────────────────────────────────────────
    webhook_base_url: str = "http://localhost:8000"
    # Public URL of the web app — used in invite links (falls back to the request's host).
    app_url: str = ""

    # ── Accounts ──────────────────────────────────────────────────────────────
    # The platform super-admin created on first boot, and their house account.
    auth_email: str = ""
    auth_password: str = ""
    house_org_name: str = "BlackSync"

    # ── Clerk (sign-in) ───────────────────────────────────────────────────────
    # When set, Clerk handles sign-in/sign-up and BlackSync links each Clerk user
    # to its own user record (accounts, roles and credits stay in BlackSync).
    clerk_secret_key: str = ""
    # Signing secret (whsec_…) of the Clerk webhook that hands us Clerk's emails (email.created), so sign-in
    # codes and alerts go out from our own sender (EMAIL_FROM, blacksync.ai) instead of the Clerk domain.
    clerk_webhook_secret: str = ""
    # Second password for the admin portal (on top of being a platform super-admin).
    admin_password: str = ""
    # Extra platform super-admins, by the email they sign in to Clerk with.
    superadmin_emails: str = ""

    # ── Email (team invites) ──────────────────────────────────────────────────
    # Without a Resend key, invites still work — the UI shows a link to share.
    resend_api_key: str = ""
    # Senders (the blacksync.ai domain is verified in Resend): account and product emails come from
    # notifications@, team invites from invites@.
    email_from: str = "BlackSync <notifications@blacksync.ai>"
    email_from_invites: str = "BlackSync <invites@blacksync.ai>"

    # ── Support (in-app help widget) ──────────────────────────────────────────
    # Model for the support assistant (any model the backend has a key for: OpenAI, Cerebras or Claude).
    # Empty = gpt-oss-120b on Cerebras when CEREBRAS_API_KEY is set, else gpt-4.1-mini.
    support_ai_model: str = ""
    support_ai_enabled: bool = True
    support_ai_max_tokens: int = 500
    support_ai_context_messages: int = 12
    # AI replies allowed per user per hour (support usage never touches calling credits).
    support_ai_hourly_limit: int = 30
    # Staff notifications by email (Resend); empty address or false turns them off.
    support_notify_email: str = "sales@blacksync.ai"
    support_email_notifications: bool = True

    @model_validator(mode="after")
    def _clean_values(self):
        """Pasted keys often carry stray spaces/quotes; a bare LiveKit host needs a scheme."""
        for name, value in list(self.__dict__.items()):
            if isinstance(value, str):
                setattr(self, name, value.strip().strip("'\"").strip())
        url = self.livekit_url
        if url and "://" not in url:
            self.livekit_url = f"wss://{url}"
        return self

    @property
    def twilio_ready(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def recording_via_twilio(self) -> bool:
        p = (self.recording_provider or "").lower()
        return p == "twilio" or (p == "" and self.twilio_ready)

    @property
    def recordings_ready(self) -> bool:
        return bool(self.recordings_s3_bucket and self.recordings_s3_access_key and self.recordings_s3_secret_key)

    @property
    def livekit_http_url(self) -> str:
        """Server-side API calls (rooms, SIP, dispatch) go over http(s), not ws(s)."""
        url = self.livekit_url
        if url.startswith("wss://"):
            return "https://" + url[len("wss://"):]
        if url.startswith("ws://"):
            return "http://" + url[len("ws://"):]
        return url

    @property
    def api_base_url(self) -> str:
        """WEBHOOK_BASE_URL with a scheme (hosts give a bare host:port on private networks)."""
        url = self.webhook_base_url.strip().rstrip("/")
        return url if "://" in url else f"http://{url}"

    @property
    def clerk_enabled(self) -> bool:
        return bool(self.clerk_secret_key)

    @property
    def superadmin_email_set(self) -> set[str]:
        emails = {e.strip().lower() for e in self.superadmin_emails.split(",") if e.strip()}
        if self.auth_email:
            emails.add(self.auth_email.strip().lower())
        return emails

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def livekit_ready(self) -> bool:
        return bool(self.livekit_url and self.livekit_api_key and self.livekit_api_secret)

    @property
    def voice_ready(self) -> bool:
        return bool(
            self.livekit_ready and self.openai_api_key
            and self.deepgram_api_key and self.cartesia_api_key
        )

    @property
    def phone_ready(self) -> bool:
        return bool(self.voice_ready and self.livekit_sip_outbound_trunk_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
