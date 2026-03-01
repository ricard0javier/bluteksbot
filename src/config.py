"""Centralised configuration — all values via os.getenv(), zero hardcoded values elsewhere."""

import os


from dotenv import load_dotenv

load_dotenv()

# ── Application ───────────────────────────────────────────────────────────────
APP_NAME: str = os.getenv("APP_NAME", "bluteksbot")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", "logs/bluteksbot.log")
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_POLLING_INTERVAL: int = int(os.getenv("TELEGRAM_POLLING_INTERVAL", "1"))
TELEGRAM_TIMEOUT: int = int(os.getenv("TELEGRAM_TIMEOUT", "30"))
TELEGRAM_ALLOWED_USER_IDS: list[int] = [
    int(uid)
    for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if uid.strip() and not uid.strip().startswith("#")
]

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017/?replicaSet=rs0")
MONGO_DB: str = os.getenv("MONGO_DB", "bluteksbot")
MONGO_COLLECTION_EVENTS: str = os.getenv("MONGO_COLLECTION_EVENTS", "events")
MONGO_COLLECTION_MEMORY: str = os.getenv("MONGO_COLLECTION_MEMORY", "memory")
MONGO_COLLECTION_DLQ: str = os.getenv("MONGO_COLLECTION_DLQ", "dlq")
MONGO_COLLECTION_IDEMPOTENCY: str = os.getenv(
    "MONGO_COLLECTION_IDEMPOTENCY", "processed"
)
MONGO_COLLECTION_CONV_HISTORY: str = os.getenv(
    "MONGO_COLLECTION_CONV_HISTORY", "conversation_history"
)

# ── LiteLLM ───────────────────────────────────────────────────────────────────
LITELLM_BASE_URL: str = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY: str = os.getenv("LITELLM_API_KEY", "sk-dummy")
LITELLM_ORCHESTRATOR_MODEL: str = os.getenv("LITELLM_ORCHESTRATOR_MODEL", "gpt-4o-mini")
LITELLM_WORKER_MODEL: str = os.getenv("LITELLM_WORKER_MODEL", "gpt-4o-mini")
LITELLM_EMBEDDING_MODEL: str = os.getenv(
    "LITELLM_EMBEDDING_MODEL", "text-embedding-3-small"
)
LITELLM_MAX_TOKENS: int = int(os.getenv("LITELLM_MAX_TOKENS", "4096"))
LITELLM_TEMPERATURE: float = float(os.getenv("LITELLM_TEMPERATURE", "0.2"))

# ── Embeddings / Vector Search ────────────────────────────────────────────────
EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "1536"))
MEMORY_TOP_K: int = int(os.getenv("MEMORY_TOP_K", "5"))

# ── Tools ─────────────────────────────────────────────────────────────────────
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
WEB_SEARCH_MAX_RESULTS: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")

CALENDAR_TIMEZONE: str = os.getenv("CALENDAR_TIMEZONE", "UTC")

CODE_EXECUTOR_TIMEOUT: int = int(os.getenv("CODE_EXECUTOR_TIMEOUT", "60"))
CODE_EXECUTOR_MAX_OUTPUT_CHARS: int = int(
    os.getenv("CODE_EXECUTOR_MAX_OUTPUT_CHARS", "5000")
)

# ── Exponential Backoff ───────────────────────────────────────────────────────
BACKOFF_BASE_SECONDS: float = float(os.getenv("BACKOFF_BASE_SECONDS", "1.0"))
BACKOFF_MAX_SECONDS: float = float(os.getenv("BACKOFF_MAX_SECONDS", "60.0"))
BACKOFF_MULTIPLIER: float = float(os.getenv("BACKOFF_MULTIPLIER", "2.0"))

# ── LangGraph / Deep Agents / LangMem ────────────────────────────────────────
DEEP_AGENT_WORKSPACE: str = os.getenv("DEEP_AGENT_WORKSPACE", "/workspace/agent_files")
LANGMEM_NAMESPACE: str = os.getenv("LANGMEM_NAMESPACE", f"{APP_NAME},memories")

# ── Summarization ─────────────────────────────────────────────────────────────
# Set to the model's INPUT context window size (not max output tokens).
# Summarization fires at ~85 % of this value; the last ~10 % of tokens are kept.
# Set to 0 to disable summarization entirely.
# only summariz chat history, not the context of the current message
SUMMARIZATION_TRIGGER_TOKENS: int = int(
    os.getenv("SUMMARIZATION_TRIGGER_TOKENS", "100000")
)

# ── LangSmith (optional observability) ───────────────────────────────────────
LANGSMITH_TRACING: str = os.getenv("LANGSMITH_TRACING", "false")
LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", APP_NAME)
