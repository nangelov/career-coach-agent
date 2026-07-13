"""`internet_search` — general web search over the Tavily provider (§5.7 / §6.19).

Search backend (locked P6 decision §6.19): **Tavily**, accessed through a **3-key
rotating pool** (:class:`~app.tools.tavily_pool.TavilyPool`) that fails over on a
dead/exhausted key and **promotes the survivor to primary** (persisted in Redis,
reusing the §6.6 LLM-router pattern). This supersedes the P1 self-hosted SearXNG
backend. When no ``TAVILY_API_KEY_*`` is set the tool returns a graceful "not
configured" result (mirroring the earlier empty-``SEARXNG_URL`` behavior).

This module is a thin **tool adapter**: it owns the ``internet_search`` schema/name
and argument validation, and delegates the actual provider/failover/caching to the
pool. Job listings are deliberately out of scope — market-signal mining lands later
in P6.

Search results are **untrusted external data**: only plain ``title``/``url``/
``snippet`` strings are extracted and truncated (by the pool). Nothing here is
executed or interpreted as instructions — full guardrails land in P10.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings, settings
from app.llm.router import RedisLike

from .base import Tool, ToolResult, ToolSchema
from .tavily_pool import TavilyNotConfiguredError, TavilyPool, TavilyPoolExhaustedError

logger = logging.getLogger(__name__)

#: Default number of results returned when the model does not specify one.
DEFAULT_MAX_RESULTS = 5
#: Hard cap on results, regardless of what the model asks for.
MAX_RESULTS_CAP = 10

_SCHEMA: ToolSchema = {
    "type": "function",
    "function": {
        "name": "internet_search",
        "description": (
            "Search the public web for up-to-date information (general knowledge, "
            "current events, company/industry facts). Returns a list of result "
            "snippets, each with a title, url, and short text excerpt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": f"Maximum results to return (1-{MAX_RESULTS_CAP}).",
                    "minimum": 1,
                    "maximum": MAX_RESULTS_CAP,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class InternetSearchTool(Tool):
    """General web search via the Tavily :class:`~app.tools.tavily_pool.TavilyPool`.

    Args:
        pool: The Tavily key pool that performs the search (failover + promotion +
            caching). When it holds no key the tool reports "not configured".
    """

    def __init__(self, *, pool: TavilyPool) -> None:
        self._pool = pool

    @classmethod
    def from_settings(
        cls,
        config: Settings = settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        redis_client: RedisLike | None = None,
    ) -> InternetSearchTool:
        """Build the tool from application config (env / HF Space secrets).

        ``redis_client`` (the app's single shared Redis client) is optional: when
        supplied it backs the pool's promote-to-primary, circuit-breaking, and result
        cache; when omitted the pool still works with in-call failover only.
        """
        pool = TavilyPool.from_settings(config, redis_client=redis_client, http_client=http_client)
        return cls(pool=pool)

    @property
    def name(self) -> str:
        return "internet_search"

    @property
    def schema(self) -> ToolSchema:
        return _SCHEMA

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult.error("'query' is required and must be a non-empty string.")

        max_results = _coerce_max_results(arguments.get("max_results"))

        try:
            results = await self._pool.search(query, max_results)
        except TavilyNotConfiguredError:
            return ToolResult.error("Internet search is not configured (set TAVILY_API_KEY_1/2/3).")
        except TavilyPoolExhaustedError as exc:
            # Every key failed (timeout / quota / auth / transport). The pool already
            # logged the per-key cause; return a graceful result so the model loop
            # continues rather than crashing.
            logger.warning("internet_search exhausted the Tavily key pool: %s", exc)
            return ToolResult.error("Search request failed.")

        return ToolResult.ok({"query": query, "results": results})


def _coerce_max_results(value: Any) -> int:
    """Clamp a model-supplied ``max_results`` into ``[1, MAX_RESULTS_CAP]``."""
    # bool is an int subclass; treat it as "unspecified" rather than 0/1.
    if not isinstance(value, int) or isinstance(value, bool):
        return DEFAULT_MAX_RESULTS
    return max(1, min(value, MAX_RESULTS_CAP))
