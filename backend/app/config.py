"""
Application configuration — single source of truth for all runtime config and secrets.

ALL secrets (HF_API_TOKEN, DATABASE_URL, JWT_SECRET_KEY, OAuth client credentials, etc.)
MUST come from environment variables or HF Space Secrets.  Never hard-code real secret values
here, and never commit a populated .env file.

The v2 .env file belongs at backend/.env (or the repo root) and is git-ignored.  In HF Spaces
use the Space Secrets panel — values are injected as environment variables at container startup.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic-settings model for all v2 runtime configuration.

    Required fields (no default) raise a clear ValidationError on startup if the
    corresponding environment variable is absent — this is intentional: fail fast
    rather than run with a missing secret.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # -------------------------------------------------------------------------
    # LLM / HF Inference
    # -------------------------------------------------------------------------
    HF_API_TOKEN: str = Field(
        ...,
        description="HuggingFace API token — required; set via env or HF Space Secret.",
    )
    LLM_PRIMARY_MODEL: str = Field(
        default="zai-org/GLM-5.2",
        description="Primary LLM model id (supports native tool-calling via HF Inference).",
    )
    LLM_SECONDARY_MODEL: str = Field(
        default="Qwen/Qwen3.6-27B",
        description="Failover LLM model id used by the multi-LLM router.",
    )
    LLM_BASE_URL: str = Field(
        default="https://api-inference.huggingface.co/v1",
        description="OpenAI-compatible base URL for HF Inference Providers.",
    )
    LLM_TIMEOUT_SECONDS: int = Field(
        default=30,
        description="Per-request LLM timeout in seconds.",
    )
    LLM_MODELS: list[str] = Field(
        default=[],
        description=(
            "Ordered LLM model list for the failover router (primary first). "
            "When empty, the router falls back to [LLM_PRIMARY_MODEL, LLM_SECONDARY_MODEL]. "
            "Set via env (JSON list) to re-prioritize without a code change (§6.6). "
            "Free/OSS models only — no paid last-resort entry."
        ),
    )
    LLM_MAX_RETRIES: int = Field(
        default=2,
        description="Router same-model retries for transient 5xx/429 before failing over (§6.6).",
    )
    LLM_RETRY_BACKOFF_SECONDS: float = Field(
        default=0.5,
        description="Base delay for the router's exponential retry backoff, in seconds.",
    )
    LLM_RETRY_BACKOFF_MAX_SECONDS: float = Field(
        default=8.0,
        description="Cap on the router's exponential retry backoff, in seconds.",
    )
    LLM_FIRST_TOKEN_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        description="Streaming first-token deadline; on breach the router fails over (§6.6).",
    )
    LLM_CIRCUIT_FAIL_THRESHOLD: int = Field(
        default=3,
        description="Consecutive-window failures before the router trips a model's circuit (§6.6).",
    )
    LLM_CIRCUIT_COOLDOWN_SECONDS: int = Field(
        default=30,
        description="How long a tripped model is skipped before it is probed again (§6.6).",
    )
    LLM_CIRCUIT_WINDOW_SECONDS: int = Field(
        default=60,
        description="Rolling window over which router failures are counted toward the threshold.",
    )
    EMBEDDING_MODEL: str = Field(
        default="Qwen/Qwen3-Embedding-8B",
        description="Sentence-transformers model for in-process embeddings (4096-dim output).",
    )

    # -------------------------------------------------------------------------
    # Datastores
    # -------------------------------------------------------------------------
    DATABASE_URL: str = Field(
        ...,
        description=(
            "Async Postgres DSN — required. "
            "Example: postgresql+asyncpg://user:password@localhost:5432/career_coach"
        ),
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL used for caching, Celery broker, and rate limiting.",
    )
    REDIS_MAX_CONNECTIONS: int = Field(
        default=10,
        description=(
            "Upper bound on the single shared redis.asyncio ConnectionPool (§4). "
            "All requests/agents acquire clients from this one pool via repositories/redis.py; "
            "no per-request Redis() clients."
        ),
    )
    SESSION_MEMORY_TTL_SECONDS: int = Field(
        default=86_400,
        description=(
            "TTL for Redis-backed per-session working memory (§4). Refreshed on every append "
            "(sliding window) so active sessions persist and idle ones expire. Applies to guest "
            "and logged-in sessions alike at this phase (durable Postgres history is P2)."
        ),
    )
    SESSION_MEMORY_MAX_MESSAGES: int = Field(
        default=100,
        description=(
            "Cap on stored messages per session key; the oldest are trimmed first so a "
            "long-running session_id does not grow Redis usage unbounded (recent turns only, §4)."
        ),
    )
    CHAT_CANCEL_TTL_SECONDS: int = Field(
        default=60,
        description=(
            "TTL for the Redis-backed per-session cancel/stop flag (§4, replaces v1's "
            "in-process active_requests dict). A short backstop so a flag that no in-flight "
            "stream ever observes self-expires and cannot cancel a future request on the "
            "same session_id; the in-flight loop also deletes it as soon as it acts on it."
        ),
    )

    # -------------------------------------------------------------------------
    # Auth / SSO
    # -------------------------------------------------------------------------
    JWT_SECRET_KEY: str = Field(
        ...,
        description="Signing key for backend-owned session JWTs — required; never commit.",
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="JWT signing algorithm.",
    )
    JWT_EXPIRE_MINUTES: int = Field(
        default=60,
        description="JWT session lifetime in minutes.",
    )
    GOOGLE_CLIENT_ID: str = Field(
        default="",
        description="Google OAuth 2.0 client id for SSO.",
    )
    GOOGLE_CLIENT_SECRET: str = Field(
        default="",
        description="Google OAuth 2.0 client secret — set via env or HF Space Secret.",
    )
    LINKEDIN_CLIENT_ID: str = Field(
        default="",
        description="LinkedIn OAuth 2.0 client id for SSO.",
    )
    LINKEDIN_CLIENT_SECRET: str = Field(
        default="",
        description="LinkedIn OAuth 2.0 client secret — set via env or HF Space Secret.",
    )

    # -------------------------------------------------------------------------
    # External APIs
    # -------------------------------------------------------------------------
    SERPAPI_API_KEY: str = Field(
        default="",
        description="SerpAPI key for Google Jobs / web search.",
    )
    SEARXNG_URL: str = Field(
        default="",
        description=(
            "Base URL of a SearXNG instance for the `internet_search` tool "
            "(OSS, self-hostable, no API key — §11 budget posture). "
            "When empty the tool returns a graceful 'not configured' result. "
            "Example: http://searxng:8080"
        ),
    )
    SEARCH_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Per-request timeout for the `internet_search` tool, in seconds.",
    )
    RAPID_API_KEY: str = Field(
        default="",
        description="RapidAPI key for supplementary job-search APIs.",
    )

    # -------------------------------------------------------------------------
    # App behaviour
    # -------------------------------------------------------------------------
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode (verbose logging, reload, etc.).",
    )
    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:3000"],
        description="CORS allowed origins for the Next.js frontend.",
    )
    GUEST_MAX_MESSAGES: int = Field(
        default=10,
        description="Maximum chat messages a guest session may send before SSO is required.",
    )
    GUEST_MAX_UPLOADS: int = Field(
        default=1,
        description="Maximum document uploads a guest session may perform.",
    )


# Module-level singleton — imported everywhere as `from app.config import settings`.
settings = Settings()
