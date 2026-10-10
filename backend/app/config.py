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
    livekit_agent_name: str = "pounce"
    # Small hosts (e.g. a 512 MB free instance): no pre-warmed job processes,
    # no turn-detector model (VAD-only end-of-turn), never report as "busy".
    low_resource_mode: bool = False

    # ── STT / TTS ─────────────────────────────────────────────────────────────
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""

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

    # ── Orange Slice ──────────────────────────────────────────────────────────
    orange_slice_api_key: str = ""

    # ── Deployment ────────────────────────────────────────────────────────────
    webhook_base_url: str = "http://localhost:8000"
    # Public URL of the web app — used in invite links (falls back to the request's host).
    app_url: str = ""

    # ── Accounts ──────────────────────────────────────────────────────────────
    # The platform super-admin created on first boot, and their house account.
    auth_email: str = ""
    auth_password: str = ""
    house_org_name: str = "BlackSync"

    # ── Email (team invites) ──────────────────────────────────────────────────
    # Without a Resend key, invites still work — the UI shows a link to share.
    resend_api_key: str = ""
    email_from: str = "BlackSync <onboarding@resend.dev>"

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
    def api_base_url(self) -> str:
        """WEBHOOK_BASE_URL with a scheme (hosts give a bare host:port on private networks)."""
        url = self.webhook_base_url.strip().rstrip("/")
        return url if "://" in url else f"http://{url}"

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
