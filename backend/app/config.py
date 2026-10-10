"""
Application settings loaded from .env

Every provider key is optional so the API boots with zero configuration —
features light up as keys are added (see GET /api/settings/status):
  • OPENAI_API_KEY                         → chat playground + post-call analysis
  • LIVEKIT_* + DEEPGRAM + CARTESIA        → browser voice test calls
  • LIVEKIT_SIP_OUTBOUND_TRUNK_ID          → real phone calls / campaigns
"""

from functools import lru_cache
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
