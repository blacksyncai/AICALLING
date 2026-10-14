"""
LLM model catalog and language support for the voice stack.

Only models this app can actually run are listed: the voice worker drives the
LLM through the LiveKit OpenAI plugin (`openai.LLM(model=…, base_url=settings.
openai_base_url)`, streaming chat completions with tool calls), and the text
playground uses the same chat-completions path. Reasoning models (o-series,
gpt-5 reasoning) are deliberately left out: they ignore `temperature` and add
latency that a live phone call can't absorb.

Voices are Cartesia sonic-3 (any voice works with any LLM here) and speech
recognition is Deepgram nova-3, so the real compatibility constraint is the
spoken LANGUAGE — see `language_mismatch()`.
"""

from __future__ import annotations

from app.config import settings

# What the runtime falls back to when an agent has no model set
# (app/agent/runtime.py, agent_worker.py).
RUNTIME_DEFAULT_MODEL = "gpt-4.1-nano"

# id, name, description, speed (only where known), tags, recommended_for.
# `recommended_for` uses agent traits the editor knows about:
#   general · booking (calendar tools) · transfer (call transfer tool) · complex_scripts
LLM_MODELS: list[dict] = [
    {
        "id": "gpt-oss-120b",
        "name": "BlackSync Super Intelligence · Ultra",
        "provider": "BlackSync",
        "description": "Runs in dedicated AI data centers on wafer-scale supercomputer chips — thousands of tokens a "
                       "second, so it answers instantly with flagship reasoning and tool use.",
        "speed": "fast",
        "tags": ["recommended", "fast"],
        "recommended_for": ["general", "booking", "complex_scripts"],
    },
    {
        "id": "qwen-3.8-27b",
        "name": "BlackSync Super Intelligence · Flash",
        "provider": "BlackSync",
        "description": "Same data-center supercomputer hardware, tuned for speed on short, high-volume calls.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": ["general"],
    },
    {
        "id": "qwen/qwen3.8-27b",
        "name": "BlackSync Ultra Fast",
        "provider": "BlackSync",
        "description": "Our quickest brain — the first word in under half a second, so conversations feel instant.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": ["general"],
    },
    {
        "id": "ministral-8b-latest",
        "name": "BlackSync Flash",
        "provider": "BlackSync",
        "description": "Quick, natural replies and reliable call tools (booking, transfers, hang-up) at low cost.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": ["general"],
    },
    {
        "id": "ministral-3b-latest",
        "name": "BlackSync Flash Lite",
        "provider": "BlackSync",
        "description": "The fastest Flash — shortest pauses, best for simple, high-volume scripts.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": [],
    },
    {
        "id": "ministral-14b-latest",
        "name": "BlackSync Flash 2.1",
        "provider": "BlackSync",
        "description": "The smartest Flash — follows longer scripts and objections better, still fast.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": ["general", "booking"],
    },
    {
        "id": "mistral-small-latest",
        "name": "BlackSync Flash Plus",
        "provider": "BlackSync",
        "description": "A bigger Flash: sharper answers and better instruction-following, with the same quick replies.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": ["general", "booking"],
    },
    {
        "id": "mistral-medium-latest",
        "name": "BlackSync Flash Pro",
        "provider": "BlackSync",
        "description": "The smartest Flash — handles long scripts, objections and tools well, and replies consistently fast.",
        "speed": "fast",
        "tags": ["recommended", "fast"],
        "recommended_for": ["general", "booking", "transfer", "complex_scripts"],
    },
    {
        "id": "gpt-4.1-mini",
        "name": "GPT-4.1 mini",
        "description": "Fast and low-cost, good at following call scripts.",
        "speed": "fast",
        "tags": ["recommended", "fast"],
        "recommended_for": ["general"],
    },
    {
        "id": "gpt-4.1",
        "name": "GPT-4.1",
        "description": "Follows long, complex prompts and uses tools (booking, transfers) most reliably.",
        "speed": "standard",
        "tags": ["recommended", "advanced"],
        "recommended_for": ["booking", "transfer", "complex_scripts"],
    },
    {
        "id": "gpt-4.1-nano",
        "name": "GPT-4.1 nano",
        "description": "Lowest latency, so replies come fastest. The default for new agents.",
        "speed": "fast",
        "tags": ["recommended", "fast"],
        "recommended_for": [],
    },
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o mini",
        "description": "Previous-generation small model. Fast and inexpensive.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": [],
    },
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "description": "Previous-generation flagship model.",
        "speed": "standard",
        "tags": ["advanced"],
        "recommended_for": [],
    },
    {
        "id": "claude-haiku-5-5",
        "name": "Claude Haiku 5.5",
        "provider": "Anthropic",
        "description": "Anthropic's fast model. Natural, concise replies at low latency.",
        "speed": "fast",
        "tags": ["fast"],
        "recommended_for": ["general"],
    },
    {
        "id": "claude-sonnet-5-5",
        "name": "Claude Sonnet 5.5",
        "provider": "Anthropic",
        "description": "Anthropic's most capable voice option. Strong at nuanced, complex conversations and tools.",
        "speed": "standard",
        "tags": ["advanced"],
        "recommended_for": ["complex_scripts"],
    },
]


ANTHROPIC_OPENAI_BASE_URL = "https://api.anthropic.com/v1"
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
# Served on Cerebras wafer-scale hardware, branded as BlackSync's own models.
CEREBRAS_MODELS = {"gpt-oss-120b", "qwen-3.8-27b"}
# Models whose chat template rejects a request with no user message (Cerebras answers 400 "No user
# query found"), e.g. the agent's opening line. The voice worker adds a short cue turn for them.
NEEDS_USER_TURN: set[str] = {"qwen-3.8-27b"}  # Claude and Mistral models are added below (same rule).
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Served on Groq's LPU hardware, branded "BlackSync Ultra Fast".
GROQ_MODELS = {"qwen/qwen3.8-27b"}
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
# Mistral models, branded "BlackSync Flash" (Ministral 3B/8B/14B, Mistral Small, Mistral Medium).
MISTRAL_MODELS = {"ministral-8b-latest", "ministral-3b-latest", "ministral-14b-latest", "mistral-small-latest",
                  "mistral-medium-latest"}


# Claude ("At least one non-system message is required") and Mistral ("Expected last role User") refuse an
# opening request too.
NEEDS_USER_TURN |= MISTRAL_MODELS | GROQ_MODELS | {m["id"] for m in LLM_MODELS if m["id"].startswith("claude-")}


def is_anthropic_model(model_id: str | None) -> bool:
    return (model_id or "").startswith("claude-")


def reasoning_effort_for(model_id: str | None) -> str | None:
    """Reasoning setting a live call wants: as little as the model allows (it's pure latency on a call)."""
    model_id = model_id or ""
    if model_id in GROQ_MODELS:
        return "none"
    if model_id.startswith("gpt-oss"):
        return "low"
    return None


def llm_endpoint(model_id: str | None) -> tuple[str, str, bool]:
    """(api_key, base_url, sends_temperature) for a chat-completions call.

    Claude models go through Anthropic's OpenAI-compatible endpoint, so the voice
    worker's OpenAI plugin and the playground drive them unchanged. They reject
    `temperature`, so it's left out for them.
    """
    if is_anthropic_model(model_id):
        return settings.anthropic_api_key, ANTHROPIC_OPENAI_BASE_URL, False
    if model_id in CEREBRAS_MODELS:
        return settings.cerebras_api_key, CEREBRAS_BASE_URL, True
    if model_id in MISTRAL_MODELS:
        return settings.mistral_api_key, MISTRAL_BASE_URL, True
    if model_id in GROQ_MODELS:
        return settings.groq_api_key, GROQ_BASE_URL, True
    return settings.openai_api_key, settings.openai_base_url, True

GROUPS: list[tuple[str, str]] = [
    ("recommended", "Recommended"),
    ("fast", "Fast"),
    ("advanced", "Advanced"),
    ("other", "Other"),
]

# Languages the editor offers. Deepgram nova-3 handles each of these (and
# "multi" = automatic code-switching); Cartesia sonic-3 speaks all of them.
LANGUAGES: list[dict] = [
    {"code": "en", "label": "English"},
    {"code": "multi", "label": "Multilingual (auto)"},
    {"code": "es", "label": "Spanish"},
    {"code": "fr", "label": "French"},
    {"code": "de", "label": "German"},
    {"code": "pt", "label": "Portuguese"},
    {"code": "it", "label": "Italian"},
    {"code": "nl", "label": "Dutch"},
    {"code": "hi", "label": "Hindi"},
    {"code": "ja", "label": "Japanese"},
]
for _lang in LANGUAGES:
    _lang.update(stt=True, tts=True)

LANGUAGE_LABELS = {lang["code"]: lang["label"] for lang in LANGUAGES}


def _base_lang(code: str | None) -> str:
    return (code or "").strip().lower().replace("_", "-").split("-")[0]


def language_mismatch(voice_language: str | None, agent_language: str | None) -> bool:
    """True when a voice's native language differs from the agent's spoken language.

    Unknown voice language or a Multilingual agent never counts as a mismatch.
    """
    voice, agent = _base_lang(voice_language), _base_lang(agent_language)
    if not voice or not agent or agent == "multi":
        return False
    return voice != agent


def model_catalog() -> list[dict]:
    """All selectable models, each with its primary `group`.

    The server's configured default model is appended under "other" if it isn't
    already in the curated list (e.g. a model on a custom OpenAI-compatible endpoint).
    """
    models = [
        {"provider": "OpenAI", **m, "status": "available", "group": m["tags"][0]}
        for m in LLM_MODELS
        if (not is_anthropic_model(m["id"]) or settings.anthropic_api_key)
        and (m["id"] not in CEREBRAS_MODELS or settings.cerebras_api_key)
        and (m["id"] not in MISTRAL_MODELS or settings.mistral_api_key)
        and (m["id"] not in GROQ_MODELS or settings.groq_api_key)
    ]
    known = {m["id"] for m in models}
    for extra in dict.fromkeys([settings.llm_model]):
        if extra and extra not in known:
            models.append({
                "id": extra, "name": "Default model", "provider": "",
                "description": "The platform's default model.", "speed": None,
                "tags": [], "recommended_for": [], "status": "available", "group": "other",
            })
    return models


def model_groups(models: list[dict]) -> list[dict]:
    """Groups that actually have members, in display order."""
    out = []
    for key, label in GROUPS:
        ids = [m["id"] for m in models if m["group"] == key]
        if ids:
            out.append({"key": key, "label": label, "models": ids})
    return out


def is_runnable_model(model_id: str) -> bool:
    return any(m["id"] == model_id for m in model_catalog())
