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
