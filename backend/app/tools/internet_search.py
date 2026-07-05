"""`internet_search` — general web search over a free/OSS SearXNG backend.

Backend choice (design §11 budget posture): **SearXNG** — an OSS metasearch engine
that is **self-hostable** (exactly like the Postgres/Redis containers) and needs
**no API key**, returning clean JSON. It is deliberately distinct from the
job-search-specific SerpAPI/Google Jobs path, which lands later in P6
(`agents/job_agent.py`). The instance URL comes from ``settings.SEARXNG_URL``
(never hard-coded); when unset the tool returns a graceful "not configured" result.

Search results are **untrusted external data**: only plain ``title``/``url``/
``snippet`` strings are extracted and truncated. Nothing here is executed or
interpreted as instructions — full guardrails land in P10.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings, settings

from .base import Tool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: Default number of results returned when the model does not specify one.
DEFAULT_MAX_RESULTS = 5
#: Hard cap on results, regardless of what the model asks for.
MAX_RESULTS_CAP = 10
#: Snippets are truncated to keep tool output compact and bounded.
SNIPPET_MAX_CHARS = 400

_SCHEMA: ToolSchema = {
    "type": "function",
    "function": {
        "name": "internet_search",
        "description": (
            "Search the public web for up-to-date information (general knowledge, "
            "current events, company/industry facts). Returns a list of result "
            "snippets, each with a title, url, and short text excerpt. Do NOT use "
            "this for job listings — a dedicated job-search tool handles those."
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
    """General web search via a SearXNG JSON endpoint.

    Args:
        base_url: SearXNG instance base URL (empty ⇒ tool reports "not configured").
        timeout: Per-request timeout in seconds.
        http_client: Optional injected ``httpx.AsyncClient`` (tests supply a
            mock-transport client so no real network call is made). When omitted a
            short-lived client is created per call.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http_client = http_client

    @classmethod
    def from_settings(
        cls,
        config: Settings = settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> InternetSearchTool:
        """Build the tool from application config (env / HF Space secrets)."""
        return cls(
            base_url=config.SEARXNG_URL,
            timeout=config.SEARCH_TIMEOUT_SECONDS,
            http_client=http_client,
        )

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

        if not self._base_url:
            return ToolResult.error(
                "Internet search is not configured (set SEARXNG_URL to a SearXNG instance)."
            )

        try:
            results = await self._search(query, max_results)
        except httpx.TimeoutException:
            # Log the swallowed upstream failure (the tool must return a graceful
            # ToolResult.error rather than crash the model loop) so real SearXNG outages
            # are observable — matching the service-layer swallowed-failure convention.
            logger.warning(
                "internet_search request timed out (url=%s)", self._base_url, exc_info=True
            )
            return ToolResult.error("Search request timed out.")
        except httpx.HTTPError as exc:
            logger.warning("internet_search request failed (url=%s)", self._base_url, exc_info=True)
            return ToolResult.error(f"Search request failed: {exc}")

        return ToolResult.ok({"query": query, "results": results})

    async def _search(self, query: str, max_results: int) -> list[dict[str, str]]:
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._http_client is None
        try:
            response = await client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            payload: Any = response.json()
        finally:
            if owns_client:
                await client.aclose()

        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(raw_results, list):
            return []

        results: list[dict[str, str]] = []
        for item in raw_results[:max_results]:
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


def _coerce_max_results(value: Any) -> int:
    """Clamp a model-supplied ``max_results`` into ``[1, MAX_RESULTS_CAP]``."""
    # bool is an int subclass; treat it as "unspecified" rather than 0/1.
    if not isinstance(value, int) or isinstance(value, bool):
        return DEFAULT_MAX_RESULTS
    return max(1, min(value, MAX_RESULTS_CAP))


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
