"""Tavily search provider — an ordered, Redis-promoted 3-key rotating pool (§5.7 / §6.19).

Tavily's free tier gives ~2-3k searches/month **per key**; three keys
(``TAVILY_API_KEY_1|2|3``, HF Space Secrets) are pooled so quota exhaustion or a
dead key does not take search down. This is deliberately the **same shape as the
§6.6 LLM failover router** — an ordered list of providers, per-provider health
tracked by a Redis :class:`~app.llm.router.CircuitBreaker`, and the surviving
provider **promoted to primary** (persisted in Redis so a dead/exhausted key is not
retried first on every call). It **reuses** that router machinery
(:class:`~app.llm.router.CircuitBreaker`, the :class:`~app.llm.router.RedisLike`
seam) rather than inventing a second mechanism.

Quota is a shared, exhaustible resource, so results are **cached in Redis** keyed on
the normalized query (§5.7: *"cache search results in Redis … never let a
user-facing turn trigger uncached crawling"*) — a short-TTL cache is enough here;
the learning-resource mining/crawl caching is a later P6 task.

**Location.** This lives in ``app/tools/`` next to its only consumer,
:class:`~app.tools.internet_search.InternetSearchTool` — it is the concrete
search-provider primitive behind the ``internet_search`` tool (cohesive with it,
just as the tool already owns its own ``httpx`` concerns), not general networking
infra. It reuses the ``llm/`` circuit-breaker/Redis pieces without depending on the
``agents``/``services`` layers.

**Secrets never logged.** The circuit-breaker and all log lines key on the *pool
index* (a stable, non-secret id), never the raw key value. The key value is only
ever placed in the outbound ``Authorization`` header.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence

import httpx

from app.config import Settings, settings
from app.llm.router import CircuitBreaker, RedisLike

logger = logging.getLogger(__name__)

#: Tavily search endpoint (a public constant, not a secret).
TAVILY_API_URL = "https://api.tavily.com/search"
#: Redis key holding the promoted primary key-index (survives across calls).
PRIMARY_INDEX_KEY = "tavily:primary_index"
#: Redis key prefix for cached raw search results (keyed on the normalized query).
CACHE_KEY_PREFIX = "tavily:cache"
#: Circuit-breaker key prefix for per-key health (keyed on index, never the secret).
CIRCUIT_KEY_PREFIX = "tavily:cb"
#: TTL for a cached search-result set, in seconds. Short — just long enough to
#: absorb repeat queries within a session and save quota, not a durable store (§5.7).
SEARCH_CACHE_TTL_SECONDS = 3600
#: Snippets are truncated to keep tool output compact and bounded (mirrors the tool).
SNIPPET_MAX_CHARS = 400


class TavilyError(Exception):
    """Base class for Tavily pool failures."""


class TavilyNotConfiguredError(TavilyError):
    """No ``TAVILY_API_KEY_*`` is set — the pool has nothing to query."""


class TavilyPoolExhaustedError(TavilyError):
    """Every key in the pool failed (or is circuit-open) for this call."""


class TavilyPool:
    """Ordered, failover-with-promotion pool over up to three Tavily API keys.

    Args:
        keys: The candidate API keys in priority order; blank entries are skipped.
        redis_client: Optional :class:`~app.llm.router.RedisLike` handle (the app's
            single shared Redis client). When supplied it backs promote-to-primary,
            per-key circuit-breaking, and result caching; when ``None`` the pool
            still works (in-call failover only) but promotion/cache/breaker are
            no-ops — the graceful degradation used when Redis is unavailable.
        breaker: Optional pre-built :class:`~app.llm.router.CircuitBreaker`; when
            omitted one is built over ``redis_client`` with ``key_prefix``
            ``"tavily:cb"`` (reusing the §6.6 router class directly).
        http_client: Optional injected ``httpx.AsyncClient`` (tests supply a
            mock-transport client). When omitted a short-lived client is created
            per request.
        timeout: Per-request timeout in seconds.
        api_url: Tavily endpoint (overridable for tests).
        cache_ttl_seconds: TTL for the Redis result cache.
    """

    def __init__(
        self,
        keys: Sequence[str],
        *,
        redis_client: RedisLike | None = None,
        breaker: CircuitBreaker | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        api_url: str = TAVILY_API_URL,
        cache_ttl_seconds: int = SEARCH_CACHE_TTL_SECONDS,
    ) -> None:
        self._keys = [key for key in keys if key and key.strip()]
        self._redis = redis_client
        if breaker is not None:
            self._breaker: CircuitBreaker | None = breaker
        elif redis_client is not None:
            self._breaker = CircuitBreaker(redis_client, key_prefix=CIRCUIT_KEY_PREFIX)
        else:
            self._breaker = None
        self._http_client = http_client
        self._timeout = timeout
        self._api_url = api_url
        self._cache_ttl = cache_ttl_seconds

    @classmethod
    def from_settings(
        cls,
        config: Settings = settings,
        *,
        redis_client: RedisLike | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> TavilyPool:
        """Build the pool from application config (env / HF Space secrets)."""
        return cls(
            [config.TAVILY_API_KEY_1, config.TAVILY_API_KEY_2, config.TAVILY_API_KEY_3],
            redis_client=redis_client,
            http_client=http_client,
            timeout=config.SEARCH_TIMEOUT_SECONDS,
        )

    @property
    def is_configured(self) -> bool:
        """Whether at least one non-blank key is present."""
        return bool(self._keys)

    async def search(self, query: str, max_results: int) -> list[dict[str, str]]:
        """Search Tavily via the pool, returning normalized ``{title, url, snippet}`` dicts.

        A Redis cache hit short-circuits the network entirely. Otherwise keys are
        tried in promotion order (skipping circuit-open ones); the first success is
        cached, promoted to primary, and returned. Raises
        :class:`TavilyNotConfiguredError` when no key is set and
        :class:`TavilyPoolExhaustedError` when every eligible key fails.
        """
        if not self._keys:
            raise TavilyNotConfiguredError("No Tavily API key configured.")

        cache_key = self._cache_key(query, max_results)
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return cached

        order, primary = await self._key_order()
        last_error: Exception | None = None
        attempted = False
        for idx in order:
            if self._breaker is not None and await self._breaker.is_open(str(idx)):
                continue
            attempted = True
            try:
                results = await self._search_one(self._keys[idx], query, max_results)
            except httpx.HTTPError as exc:
                # Key failure (timeout, transport error, or a non-2xx incl. quota/auth):
                # count it against the key's circuit and fail over to the next key.
                logger.warning("Tavily key #%d failed: %s", idx, exc)
                if self._breaker is not None:
                    await self._breaker.record_failure(str(idx))
                last_error = exc
                continue
            if self._breaker is not None:
                await self._breaker.record_success(str(idx))
            if idx != primary:
                await self._promote(idx)
            await self._cache_set(cache_key, results)
            return results

        if not attempted:
            raise TavilyPoolExhaustedError("All Tavily keys are circuit-open.")
        raise TavilyPoolExhaustedError(
            "All Tavily keys failed to serve the request."
        ) from last_error

    async def _search_one(self, api_key: str, query: str, max_results: int) -> list[dict[str, str]]:
        """Issue one Tavily request with ``api_key`` and normalize the response."""
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._http_client is None
        try:
            response = await client.post(
                self._api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                await client.aclose()
        return _normalize(payload, max_results)

    # -- promotion / ordering ------------------------------------------------

    async def _key_order(self) -> tuple[list[int], int]:
        """Return the try-order (promoted primary first) and the current primary index."""
        primary = 0
        if self._redis is not None:
            raw = await self._redis.get(PRIMARY_INDEX_KEY)
            if raw is not None:
                try:
                    candidate = int(raw)
                except (TypeError, ValueError):
                    candidate = 0
                if 0 <= candidate < len(self._keys):
                    primary = candidate
        order = [primary, *(i for i in range(len(self._keys)) if i != primary)]
        return order, primary

    async def _promote(self, idx: int) -> None:
        """Persist ``idx`` as the new primary so it is tried first on later calls."""
        if self._redis is None:
            return
        await self._redis.set(PRIMARY_INDEX_KEY, str(idx))

    # -- caching -------------------------------------------------------------

    def _cache_key(self, query: str, max_results: int) -> str:
        normalized = " ".join(query.lower().split())
        digest = hashlib.sha256(f"{normalized}|{max_results}".encode()).hexdigest()
        return f"{CACHE_KEY_PREFIX}:{digest}"

    async def _cache_get(self, key: str) -> list[dict[str, str]] | None:
        if self._redis is None:
            return None
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, list) else None

    async def _cache_set(self, key: str, results: list[dict[str, str]]) -> None:
        if self._redis is None:
            return
        await self._redis.set(key, json.dumps(results, ensure_ascii=False), ex=self._cache_ttl)


def _normalize(payload: object, max_results: int) -> list[dict[str, str]]:
    """Extract ``{title, url, snippet}`` dicts from a Tavily JSON payload (untrusted).

    Only plain strings are kept and snippets truncated; a malformed/unexpected shape
    yields ``[]`` rather than raising — the response is untrusted external data.
    """
    raw = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(raw, list):
        return []
    results: list[dict[str, str]] = []
    for item in raw[:max_results]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": _truncate(str(item.get("content", "")), SNIPPET_MAX_CHARS),
            }
        )
    return results


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
