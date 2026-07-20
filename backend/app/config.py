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
    # Input guardrail — jailbreak / prompt-injection classifier (S8, §7.4)
    # -------------------------------------------------------------------------
    INJECTION_CLASSIFIER_MODEL: str = Field(
        default="meta-llama/Llama-Prompt-Guard-2-86M",
        description=(
            "HF text-classification model for the real input jailbreak/prompt-injection "
            "guardrail (S8, §7.4). A small Prompt-Guard-family model run **in-process** via "
            "`transformers` (same no-per-call-cost posture as the in-process embeddings, §6) — "
            "no paid inference dependency. Lazy-loaded on first use; when the model / ML stack "
            "is unavailable the classifier fails open to the regex deny-list pre-filter "
            "(logged at ERROR so a misconfigured deploy is detectable). NOTE: this default is a "
            "**gated** HF repo — the runtime needs an HF_TOKEN whose account has accepted the "
            "model licence, else the download fails and the gate silently degrades to the "
            "deny-list. Provision such a token, or override this with an **ungated** equivalent "
            "(e.g. a `protectai/deberta-*-prompt-injection` model)."
        ),
    )
    INJECTION_CLASSIFIER_THRESHOLD: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Malicious-probability threshold (>=) at which the injection classifier blocks a "
            "turn. Tune for low false-positives on legitimate career questions (§7.4). The "
            "regex deny-list still runs as a cheap fast-path pre-filter ahead of the model."
        ),
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
    POSTGRES_MAX_CONNECTIONS: int = Field(
        default=5,
        description=(
            "Upper bound on the single shared SQLAlchemy async engine pool (§4). "
            "Applied as pool_size with max_overflow=0 so the total number of Postgres "
            "connections never exceeds this cap. All requests/agents acquire sessions "
            "from this one pool via repositories/postgres.py; no per-request engines."
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
    GUEST_MEMORY_TTL_SECONDS: int = Field(
        default=86_400,
        description=(
            "TTL for a guest's Redis-only personalization store (P9-07, §5.4 — 'Guests: "
            "personalization is session-only (Redis, ephemeral)'). Mirrors the guest session "
            "lifetime (GUEST_SESSION_TTL_SECONDS default 24h) so ephemeral personalization never "
            "outlives the guest session that produced it; refreshed on each write (sliding). On "
            "upgrade-to-account it is migrated to the durable Postgres stores, then left to expire."
        ),
    )
    GUEST_MEMORY_MAX_MEMORIES: int = Field(
        default=50,
        description=(
            "Cap on learned-memory strings kept in a guest's Redis personalization store "
            "(P9-07); the oldest are dropped first so a long guest session does not grow Redis "
            "usage unbounded. Ephemeral and small — durable per-user memory (an account) is "
            "unbounded by contrast (§5.4)."
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
    CONSENT_POLICY_VERSION: str = Field(
        default="2026-07-13",
        description=(
            "Current Terms-of-Service + Privacy-Notice policy version (§6.22 / §7.6). The "
            "single source of truth for the consent gate: no session is minted without "
            "acceptance of this version. Recorded against the ``users`` row at SSO login "
            "(with a timestamp) and stamped on a guest session record for its lifetime. "
            "**Bumping this value is the re-consent mechanism** — a returning SSO user whose "
            "stored ``consent_policy_version`` no longer matches re-accepts on their next "
            "login (the login screen always re-shows the checkbox). A plain string (a date "
            "or semver); overridable via env when the notice text changes (SEC-07)."
        ),
    )
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
    OAUTH_REDIRECT_BASE_URL: str = Field(
        default="http://localhost:3000",
        description=(
            "Public base URL of the *frontend / Next origin the BFF runs on* (scheme + host, "
            "no trailing slash). Since SEC-03 the backend publishes no host port, so the OIDC "
            "redirect (callback) URI — derived as ``<base>/api/auth/callback/{provider}`` "
            "(§7.1 'redirect URIs locked to the Space domain') — must resolve on the "
            "browser-reachable Next origin, where the BFF callback Route Handler receives it "
            "and forwards to the backend server-side. Never hard-coded per provider. Locally "
            "this is ``http://localhost:3000``; in HF Spaces the Space domain (which *is* the "
            "frontend origin). The exact same value must be registered in the provider console."
        ),
    )
    OAUTH_POST_LOGIN_REDIRECT: str = Field(
        default="http://localhost:3000/auth/callback",
        description=(
            "URL the backend callback appends the minted session JWT to (in the URL "
            "*fragment*: ``#access_token=...&token_type=bearer&...``). This redirect is "
            "consumed **server-side only** by the Next.js BFF callback Route Handler (SEC-04): "
            "it reads the token out of the fragment inside its Node process, sets the httpOnly "
            "cookie, and redirects the *browser* to a clean URL. The browser never sees this "
            "fragment, so the token never reaches browser JS, history, server logs, or the "
            "Referer header."
        ),
    )
    OAUTH_METADATA_URLS: dict[str, str] = Field(
        default={
            "google": "https://accounts.google.com/.well-known/openid-configuration",
            "linkedin": "https://www.linkedin.com/oauth/.well-known/openid-configuration",
        },
        description=(
            "Per-provider OIDC discovery (``.well-known/openid-configuration``) URLs. These "
            "are public provider constants (not secrets); overridable via env for testing / "
            "future providers. The set of keys is the set of supported providers."
        ),
    )
    OAUTH_SCOPES: str = Field(
        default="openid email profile",
        description=(
            "Space-separated OIDC scopes requested at login — kept minimal (§7.1). "
            "LinkedIn *profile import* (extra scopes + stored token) is a separate opt-in "
            "feature, deliberately not requested here."
        ),
    )
    OAUTH_STATE_TTL_SECONDS: int = Field(
        default=600,
        description=(
            "TTL for a pending OIDC login transaction (state → PKCE verifier + nonce), "
            "stored server-side between ``/login`` and ``/callback``. Short (10 min) — it "
            "only needs to outlive the user's time on the provider consent screen. The "
            "record is single-use (consumed on callback) to prevent replay."
        ),
    )
    USER_SESSION_TTL_SECONDS: int = Field(
        default=86_400,
        description=(
            "TTL for the Redis-backed session **record** of a logged-in user (§4 "
            "``sessions`` / §7.1). Distinct from the bearer JWT lifetime "
            "(JWT_EXPIRE_MINUTES): the JWT is the short-lived credential while this record "
            "anchors the server-side session and is what ``POST /api/auth/logout`` deletes "
            "for immediate revocation. Kept >= the JWT lifetime."
        ),
    )
    UPGRADE_TICKET_TTL_SECONDS: int = Field(
        default=300,
        description=(
            "TTL for a guest→account upgrade ticket (P3-03), stored server-side by "
            "``POST /api/auth/upgrade`` and consumed at ``/login`` to carry the guest's "
            "active session across SSO. Short (5 min) — it only needs to outlive the "
            "click-to-login window. Single-use (consumed on ``/login``) to prevent replay."
        ),
    )

    # -------------------------------------------------------------------------
    # External APIs
    # -------------------------------------------------------------------------
    SERPAPI_API_KEY: str = Field(
        default="",
        description="SerpAPI key for Google Jobs / web search.",
    )
    TAVILY_API_KEY_1: str = Field(
        default="",
        description=(
            "Primary Tavily API key for the `internet_search` tool (§5.7 / §6.19). "
            "Set via env / HF Space Secret; never hard-coded or logged. Free-tier quota is "
            "~2-3k searches/month per key — three keys form an ordered rotating pool with "
            "failover + promote-to-primary (persisted in Redis, reusing the §6.6 router "
            "pattern). When all three are blank the tool returns 'not configured'."
        ),
    )
    TAVILY_API_KEY_2: str = Field(
        default="",
        description="Second Tavily API key in the rotating pool (§5.7 / §6.19) — env/secret only.",
    )
    TAVILY_API_KEY_3: str = Field(
        default="",
        description="Third Tavily API key in the rotating pool (§5.7 / §6.19) — env/secret only.",
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
        description=(
            "Maximum chat messages a guest session may send before SSO is required "
            "(§6 Decision 8: '10 messages + 1 document upload per guest session'). "
            "Enforced in Redis, keyed on the guest session_id, over the guest window below."
        ),
    )
    GUEST_MAX_UPLOADS: int = Field(
        default=1,
        description=(
            "Maximum document uploads a guest session may perform (§6 Decision 8). "
            "Enforced in Redis, keyed on the guest session_id, over the guest window below."
        ),
    )
    GUEST_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=86_400,
        description=(
            "Window (seconds) over which the guest message/upload caps apply — the guest "
            "session lifetime (default 24h, matching GUEST_SESSION_TTL_SECONDS). A guest's "
            "10-message / 1-upload budget is a per-session cap: the Redis counter is created "
            "on the first action and expires with the session, so an abandoned guest's "
            "counters self-clean. Kept equal to the guest session TTL by default."
        ),
    )
    USER_MAX_MESSAGES_PER_WINDOW: int = Field(
        default=120,
        description=(
            "Per-user chat-message rate limit over USER_RATE_LIMIT_WINDOW_SECONDS (§7 "
            "'per-session/user rate limits in Redis'). Logged-in users are limited far more "
            "generously than guests (default 120/hour vs a guest's 10/session): a fixed-window "
            "counter keyed on users.id that resets each window, guarding against abuse without "
            "throttling normal use."
        ),
    )
    USER_MAX_UPLOADS_PER_WINDOW: int = Field(
        default=20,
        description=(
            "Per-user document-upload rate limit over USER_RATE_LIMIT_WINDOW_SECONDS. "
            "Generous relative to a guest's single upload (default 20/hour), keyed on users.id."
        ),
    )
    USER_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=3_600,
        description=(
            "Fixed window (seconds, default 1h) for the per-user message/upload rate limits. "
            "The Redis counter is created on the first action of a window and expires after "
            "this many seconds, so the user's budget resets each window (unlike the guest cap, "
            "which is per-session)."
        ),
    )
    GUEST_SESSION_TTL_SECONDS: int = Field(
        default=86_400,
        description=(
            "TTL for the Redis-backed guest session **record** created by "
            "POST /api/auth/guest (§7.1 / §9). Distinct from the bearer JWT lifetime "
            "(JWT_EXPIRE_MINUTES): the JWT is the short-lived credential, while this record "
            "anchors the server-side guest session and its rate-limit state (P3-04) for "
            "the whole guest window. Kept >= the JWT lifetime so the session (and its "
            "10-message / 1-upload counters) survives a token refresh."
        ),
    )

    # -------------------------------------------------------------------------
    # Per-IP + per-tool rate limits (P10-05, §7 / §7.5)
    # -------------------------------------------------------------------------
    TRUSTED_PROXIES: list[str] = Field(
        default=[],
        description=(
            "Allowlist of trusted reverse-proxy IPs / CIDR networks in front of the app "
            "(§7.5). The client IP for per-IP rate limiting is read from ``X-Forwarded-For`` "
            "**only** when the immediate peer is in this allowlist — otherwise the header is "
            "ignored and the direct peer address is used, so an untrusted client cannot spoof "
            "its source IP to evade the limit. Empty by default (safe: XFF never trusted, peer "
            "always used). On HF Spaces set this to the platform proxy IP/subnet so the real "
            "client IP is recovered. Accepts single IPs (``10.0.0.1``) or CIDRs (``10.0.0.0/8``)."
        ),
    )
    IP_MAX_REQUESTS_PER_WINDOW: int = Field(
        default=300,
        description=(
            "Per-IP request cap over IP_RATE_LIMIT_WINDOW_SECONDS (§7.5 defense-in-depth). "
            "Runs *alongside* the per-session/per-user limits so a script farming fresh guest "
            "sessions from one source IP is still bounded. Generous relative to a single "
            "session's budget (a shared NAT/office egress may host many legitimate users), yet "
            "far below what a session-farming abuser needs. NOTE: this is a general request "
            "limit, not the S9 guest-session-creation bot gate (Altcha/PoW) — that is P12."
        ),
    )
    IP_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=3_600,
        description=(
            "Fixed window (seconds, default 1h) for the per-IP request cap (§7.5). The Redis "
            "counter is created on the first request of a window and expires after this many "
            "seconds, so the per-IP budget resets each window."
        ),
    )
    TOOL_MAX_CALLS_PER_WINDOW: int = Field(
        default=30,
        description=(
            "Per-tool invocation cap over TOOL_RATE_LIMIT_WINDOW_SECONDS, keyed on the "
            "caller (session/user) **and** the tool name (§7 / §7.5). Bounds a single "
            "conversation from triggering unbounded external/tool calls (cost + abuse control) "
            "independent of the message-count limit. A hit degrades gracefully — the model "
            "receives a rate-limit tool result and wraps up the turn (it never crashes the graph)."
        ),
    )
    TOOL_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=3_600,
        description=(
            "Fixed window (seconds, default 1h) for the per-tool invocation cap (§7.5). The "
            "Redis counter is created on the first call of a window and expires after this many "
            "seconds, so a caller's per-tool budget resets each window."
        ),
    )

    # -------------------------------------------------------------------------
    # Document ingestion (CV upload — §5.1 / §5.3)
    # -------------------------------------------------------------------------
    CV_UPLOAD_MAX_BYTES: int = Field(
        default=10 * 1024 * 1024,
        description=(
            "Maximum accepted CV upload size in bytes (default 10 MiB) for "
            "POST /api/profile/cv (§5.1). Enforced by the profile-ingest service before the "
            "file is base64-encoded and handed to the Celery parse task, so an oversized "
            "upload is rejected (413) in-request rather than tying up a worker."
        ),
    )

    # -------------------------------------------------------------------------
    # Market intelligence (role requirements — §5.6 / §5.7)
    # -------------------------------------------------------------------------
    ROLE_PROFILE_STALE_AFTER_SECONDS: int = Field(
        default=7 * 86_400,
        description=(
            "Staleness window (seconds, default 7d) for a cached role_profiles row. "
            "GET /api/roles/{role}/requirements still returns a stale-but-available profile "
            "at 200, but enqueues a background mine_role Celery job to refresh it — the "
            "non-blocking 'periodic refresh of stale profiles' (§5.6). Never triggers a "
            "blocking re-mine on the request path (§7.5)."
        ),
    )
    ROLE_REQUIREMENTS_CACHE_TTL_SECONDS: int = Field(
        default=3_600,
        description=(
            "TTL (seconds, default 1h) for the Redis-cached serialized role-requirements "
            "response (§5.6/§5.7 'cache hot roles'). Keyed on the normalized role so a second "
            "request for the same hot role is served from Redis without re-hitting Postgres."
        ),
    )

    # -------------------------------------------------------------------------
    # Observability — OpenTelemetry tracing (§6.26 / §7.8, P11)
    # -------------------------------------------------------------------------
    OTEL_ENABLED: bool = Field(
        default=False,
        description=(
            "Master switch for OpenTelemetry tracing (§7.8). Default OFF so local dev, CI and "
            "unit tests run with a no-op tracer (nothing exported, ~zero overhead). Set true in "
            "a deployed Space to emit traces across FastAPI, the LangGraph node graph and Celery "
            "tasks. When on but no OTLP endpoint is set, spans are dropped (or console-dumped "
            "via OTEL_CONSOLE_EXPORT) — enabling never requires a live backend."
        ),
    )
    OTEL_SERVICE_NAME: str = Field(
        default="career-coach-agent",
        description="OTel resource service.name attached to every exported span (§7.8).",
    )
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="",
        description=(
            "OTLP/HTTP traces endpoint (§7.8) — a free-tier hosted backend (Grafana Cloud / "
            "Honeycomb) or the local Collector (http://otel-collector:4318). Vendor-neutral OTLP; "
            "no vendor SDK. ``/v1/traces`` is appended if absent. Empty → no export (drop/console)."
        ),
    )
    OTEL_EXPORTER_OTLP_HEADERS: str = Field(
        default="",
        description=(
            "Comma-separated OTLP export headers (the standard ``k1=v1,k2=v2`` form), e.g. the "
            "backend's API key: ``api-key=...`` / ``authorization=Bearer ...``. Set via env / HF "
            "Space Secret — never hard-coded. Empty when the endpoint needs no auth (Collector)."
        ),
    )
    OTEL_CONSOLE_EXPORT: bool = Field(
        default=False,
        description=(
            "When OTEL_ENABLED and no OTLP endpoint is set, dump spans to the console (§7.8). A "
            "local-only verification aid so tracing can be seen end-to-end without any backend; "
            "off by default. Ignored when OTEL_EXPORTER_OTLP_ENDPOINT is set (OTLP wins)."
        ),
    )

    # -------------------------------------------------------------------------
    # Observability — Sentry error tracking (§6.24 / §7.7, S15)
    # -------------------------------------------------------------------------
    SENTRY_DSN: str = Field(
        default="",
        description=(
            "Sentry project DSN (§6.24 / §7.7). **Empty by default = Sentry is a complete "
            "no-op** — this is the default-off gate (mirroring OTEL's disabled posture): local "
            "dev, CI and unit tests never talk to Sentry and need no DSN. Set to the project DSN "
            "created in the Sentry dashboard (via env / HF Space Secret — never hard-coded) to "
            "enable unhandled-exception alerting across FastAPI and Celery. PII scrubbing is "
            "always on when enabled (send_default_pii=False + a redacting before_send)."
        ),
    )
    SENTRY_ENVIRONMENT: str = Field(
        default="",
        description=(
            "Sentry ``environment`` tag attached to every event (e.g. ``production`` / "
            "``staging``) so issues can be filtered per deploy. Empty → the SDK's default. "
            "Only used when SENTRY_DSN is set."
        ),
    )
    SENTRY_TRACES_SAMPLE_RATE: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Sentry performance-tracing sample rate (§6.24). Default **0** — Sentry is the "
            "*error* channel; distributed tracing / APM is OTel's job (§7.8), so we do not "
            "double-pay for Sentry transaction spans. Raise only if Sentry-side performance "
            "monitoring is ever wanted; sampled transactions are PII-scrubbed too "
            "(before_send_transaction)."
        ),
    )

    # -------------------------------------------------------------------------
    # Data retention (§6.18 / §7.6 — SSO-user retention purge, S14)
    # -------------------------------------------------------------------------
    RETENTION_PURGE_AFTER_DAYS: int = Field(
        default=30,
        description=(
            "Retention window (days, default 30) after an SSO user's last activity before "
            "the periodic retention-purge Celery task erases their entire footprint "
            "(conversations / CVs / profiles / memories / PDPs / dashboard) via the same "
            "cascading delete as DELETE /api/me (§6.18 'Retention → SSO users: 1 month'). "
            "'Last activity' = the most recent messages.created_at across the user's "
            "conversations, falling back to users.created_at for a user who never chatted. "
            "Guests are Redis-only and expire with their session TTL — no purge needed."
        ),
    )


# Module-level singleton — imported everywhere as `from app.config import settings`.
settings = Settings()
