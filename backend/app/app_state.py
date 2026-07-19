"""Shared ``app.state`` attribute keys — the one contract between the composition
root (``app.bootstrap`` / the lifespan), the FastAPI dependencies, and the shutdown
teardown in ``app.main``.

These three modules must agree on the exact attribute names used to stash and later
recover the shared pools/service on ``FastAPI.state``. Centralizing the names removes
the silent-failure trap of bare string literals: a rename/typo in one place would make
the ``getattr(..., None)`` elsewhere quietly return ``None`` — and because pool-close
and durable persistence are best-effort, that failure is *silent* (a leaked pool on
shutdown, or persistence quietly disabled), not an error. Referencing a single
:class:`AppStateKeys` member everywhere makes such a drift a typo the type checker /
import machinery catches instead.
"""

from __future__ import annotations

from enum import StrEnum


class AppStateKeys(StrEnum):
    """Attribute names stashed on :attr:`fastapi.FastAPI.state` and read across modules.

    :class:`~enum.StrEnum` members *are* plain ``str`` values, so they can be passed
    directly to ``getattr`` / ``setattr`` on ``app.state``.
    """

    #: The single shared Postgres engine/pool provider (built eagerly in the lifespan).
    PG_PROVIDER = "pg_provider"
    #: The single shared Redis pool provider (built by the composition root; closed on shutdown).
    REDIS_PROVIDER = "redis_provider"
    #: The app-scoped :class:`~app.services.chat.ChatService`, built once and cached.
    CHAT_SERVICE = "chat_service"
    #: The app-scoped :class:`~app.services.auth.GuestAuthService`, built once and cached.
    AUTH_SERVICE = "auth_service"
    #: The app-scoped :class:`~app.services.auth.SsoAuthService` (OIDC login), built once.
    SSO_AUTH_SERVICE = "sso_auth_service"
    #: The app-scoped :class:`~app.services.auth.SessionAuthenticator` (verify/logout), cached.
    SESSION_AUTHENTICATOR = "session_authenticator"
    #: The app-scoped :class:`~app.services.guest_upgrade.GuestUpgradeService` (P3-03), cached.
    GUEST_UPGRADE_SERVICE = "guest_upgrade_service"
    #: The app-scoped :class:`~app.services.rate_limiting.RateLimitService` (P3-04), cached.
    RATE_LIMIT_SERVICE = "rate_limit_service"
    #: The app-scoped :class:`~app.security.client_ip.ClientIpResolver` (P10-05 per-IP), cached.
    CLIENT_IP_RESOLVER = "client_ip_resolver"
    #: The app-scoped :class:`~app.services.user_store.UserStore` (admin authz, P3-05), cached.
    USER_STORE = "user_store"
    #: The app-scoped :class:`~app.services.feedback.FeedbackReader` (admin read, P3-05), cached.
    FEEDBACK_READER = "feedback_reader"
    #: The app-scoped :class:`~app.services.profile_ingest.ProfileIngestService` (P5-04), cached.
    PROFILE_INGEST_SERVICE = "profile_ingest_service"
    #: The app-scoped :class:`~app.services.profile_store.ProfileStore` (P5-05 get/put), cached.
    PROFILE_STORE = "profile_store"
    #: The app-scoped :class:`~app.services.jobs.JobStatusService` (P5-06 poll), cached.
    JOB_STATUS_SERVICE = "job_status_service"
    #: The app-scoped :class:`~app.services.account.AccountService` (SEC-05 erase/export), cached.
    ACCOUNT_SERVICE = "account_service"
    #: The app-scoped :class:`~app.services.roles.RolesService` (P6-07 role requirements), cached.
    ROLES_SERVICE = "roles_service"
    #: The app-scoped :class:`~app.services.pdp.PdpService` (P7-03 PDP generation), cached.
    PDP_SERVICE = "pdp_service"
    #: The app-scoped :class:`~app.services.dashboard.DashboardService` (P8-02 CRUD), cached.
    DASHBOARD_SERVICE = "dashboard_service"
    #: The app-scoped :class:`~app.services.message_feedback.MessageFeedbackStore` (P9-01), cached.
    MESSAGE_FEEDBACK_STORE = "message_feedback_store"
    #: The app-scoped :class:`~app.services.memory.MemoryService` (P9-05 memory panel), cached.
    MEMORY_SERVICE = "memory_service"
