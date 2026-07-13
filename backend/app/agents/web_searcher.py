"""Web Searcher + Crawler worker — search the open web, crawl a few hits, cite (design §3).

This replaces the P4-02 ``web_search_node`` stub with the real *retrieval* worker design §3
describes (*"Web Searcher + Crawler: general internet search, and crawl a few of the top
result pages to extract more content than a snippet gives, returning grounded material +
citations"*). Like the sibling RAG worker (P4-04) its job is **retrieval + citation only** —
it does *not* call the LLM to compose an answer; that synthesis is the responder's job
(P4-05/06). It hands the responder grounded material (search snippets + short crawled
excerpts) plus one :class:`~app.agents.state.Citation` per result.

**What it does, in order.**

1. Take the current turn's ``user_message`` as the query and run the
   :class:`~app.tools.internet_search.InternetSearchTool` (Tavily 3-key pool, §5.7 / §6.19)
   **directly** — the worker knows what to search for from the state, so it calls the tool
   rather than round-tripping through the LLM tool-call loop (same posture ``rag_agent``
   uses calling ``hybrid_search`` directly). There is no second search client.
2. **Crawl** a small, capped number of the top result URLs (``DEFAULT_CRAWL_PAGES``): a
   bounded ``GET`` per page through the **SSRF guard** (:mod:`app.net.ssrf_guard`, design
   §7.2) — http(s)-only, resolved-IP-validated, per-hop-re-validated redirects, capped
   timeout, capped response bytes — from which **plain text** is extracted with a stdlib
   :mod:`html.parser` pass (tags / scripts / styles stripped) and truncated to a bounded
   length. No new parsing dependency is pulled in (budget / OSS posture, design §11; keeps
   the curated CI install unchanged).
3. Map every search result to a :class:`Citation` (title / url / snippet) and bundle the
   snippets + crawled excerpts into :attr:`WorkerResult.content` as grounded material.

**Crawled content is untrusted data (design §7 / §10).** The fetched page text is treated as
**inert** — it is only ever placed into ``content`` / ``citations`` text fields for the
responder to summarise and cite. Nothing here executes it, feeds it back into a tool-call /
routing decision, or lets it influence which workers run. This worker calls no tools *based
on* crawled text, so it cannot become an injection vector; the full injection classifier
lands in P10 — this task's job is only to *not create* an obvious one.

**Fail-soft (a crawl must never crash the turn).** A per-URL failure (timeout, 404, non-HTML,
oversized body) is skipped, not fatal — the other results still produce citations. A
whole-worker failure (search unavailable / SearXNG "not configured") returns a
:class:`WorkerResult` carrying an ``error`` and no citations rather than raising, mirroring the
RAG worker's and planner's safe-default posture.

**Dependency injection (test seam, mirrors P4-04).** :func:`search_and_crawl` takes a
:class:`SearchRunner` (the capability :class:`~app.tools.internet_search.InternetSearchTool`
satisfies structurally) and an optional ``httpx.AsyncClient`` by keyword — never constructing
a search backend itself. :func:`make_web_search_node` binds them into a LangGraph node
closure; ``build_graph`` wires the settings-configured tool in production and unit tests inject
a fake search tool + a mock ``httpx`` transport so no real network call is made.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

import httpx

from app.agents.state import AgentState, Citation, WorkerName, WorkerResult
from app.ingestion.html_text import html_to_text
from app.net.ssrf_guard import build_guarded_client, read_capped
from app.tools.base import ToolResult
from app.tools.internet_search import InternetSearchTool

logger = logging.getLogger(__name__)

__all__ = [
    "CRAWL_MAX_BYTES",
    "CRAWL_TIMEOUT_SECONDS",
    "DEFAULT_CRAWL_PAGES",
    "DEFAULT_MAX_RESULTS",
    "EXTRACT_MAX_CHARS",
    "SearchRunner",
    "make_web_search_node",
    "search_and_crawl",
]

#: How many search results to request from the search backend for a turn.
DEFAULT_MAX_RESULTS = 5
#: How many of the top results to actually crawl (bounded fan-out — no unbounded fetch).
DEFAULT_CRAWL_PAGES = 3
#: Per-page crawl timeout, in seconds (bounded so one slow host can't stall the turn).
CRAWL_TIMEOUT_SECONDS = 8.0
#: Hard cap on bytes read from a single crawled page (bounds memory per turn).
CRAWL_MAX_BYTES = 2_000_000
#: Max characters kept from one crawled page's extracted text (bounds responder context).
EXTRACT_MAX_CHARS = 2_000
#: Max characters kept per citation snippet.
SNIPPET_MAX_CHARS = 400


@runtime_checkable
class SearchRunner(Protocol):
    """The search capability this worker needs: run a query, return a :class:`ToolResult`.

    A structural :class:`~typing.Protocol` (not a hard dependency on the concrete
    :class:`~app.tools.internet_search.InternetSearchTool`) so the worker depends on a
    *capability* — the SearXNG tool satisfies it in production and unit tests inject a
    scripted fake. Mirrors the RAG worker's ``SessionProvider`` seam (P4-04).
    """

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult: ...


async def search_and_crawl(
    state: AgentState,
    *,
    search_tool: SearchRunner,
    http_client: httpx.AsyncClient | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    max_crawl: int = DEFAULT_CRAWL_PAGES,
    crawl_timeout: float = CRAWL_TIMEOUT_SECONDS,
) -> WorkerResult:
    """Search the web + crawl the top hits, returning grounded material + citations (design §3).

    Runs ``search_tool`` with a query derived from ``state.user_message``, crawls up to
    ``max_crawl`` of the returned URLs for richer text, and returns a :class:`WorkerResult`
    whose ``content`` bundles the snippets/excerpts and whose ``citations`` carry one
    title/url/snippet per result. Fails soft: search failure yields a ``WorkerResult`` with
    ``error`` set and no citations; a per-URL crawl failure is skipped (never raises out of
    the node). Crawled text is inert data — only surfaced in ``content`` / ``citations``.
    """
    query = state.user_message.strip()
    if not query:
        return WorkerResult(worker=WorkerName.WEB_SEARCH)

    tool_result = await search_tool.run({"query": query, "max_results": max_results})
    if tool_result.is_error:
        return WorkerResult(worker=WorkerName.WEB_SEARCH, error=_error_message(tool_result))

    results = _parse_results(tool_result)
    if not results:
        return WorkerResult(worker=WorkerName.WEB_SEARCH)

    extracts = await _crawl_top_results(
        results, http_client, max_crawl=max_crawl, timeout=crawl_timeout
    )

    citations = [_to_citation(r) for r in results]
    return WorkerResult(
        worker=WorkerName.WEB_SEARCH,
        content=_bundle(results, extracts),
        citations=citations,
        data={"result_count": len(results), "crawled_count": len(extracts)},
    )


def make_web_search_node(
    *,
    search_tool: SearchRunner | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    max_crawl: int = DEFAULT_CRAWL_PAGES,
) -> Any:
    """Build the LangGraph ``web_search`` node closure, binding its collaborators (P4-04 pattern).

    The returned coroutine is a LangGraph node: it runs :func:`search_and_crawl` and adapts the
    :class:`WorkerResult` into the ``{"worker_results": ..., "citations": ...}`` partial update
    the graph's fan-in reducers (P4-01) fold in — the same shape the P4-02 stub produced.

    ``search_tool`` defaults to the settings-configured
    :class:`~app.tools.internet_search.InternetSearchTool` (built lazily *per call*, not at
    import; when no ``TAVILY_API_KEY_*`` is set the tool reports "not configured" and this
    worker fails soft). The chat wiring (``bootstrap``) instead injects a redis-backed tool so
    the pool's promotion/cache use the shared pool. ``http_client`` defaults to a short-lived
    per-call client for the crawl step, matching the search tool's own pattern. Both are
    injected as fakes/mock-transport clients by unit tests so no real network call is made.
    """

    async def web_search_node(state: AgentState) -> dict[str, Any]:
        tool = search_tool or InternetSearchTool.from_settings()
        result = await search_and_crawl(
            state,
            search_tool=tool,
            http_client=http_client,
            max_results=max_results,
            max_crawl=max_crawl,
        )
        return _node_update(result)

    return web_search_node


def _node_update(result: WorkerResult) -> dict[str, Any]:
    """Adapt a :class:`WorkerResult` into the web-search node's partial state update.

    Writes the result under the worker's own key (key-wise merge — no clobbering) and
    contributes its citations to the list-concatenated ``citations`` slice (P4-01 reducers).
    """
    return {
        "worker_results": {WorkerName.WEB_SEARCH.value: result},
        "citations": list(result.citations),
    }


def _parse_results(tool_result: ToolResult) -> list[dict[str, str]]:
    """Extract the ``results`` list from a successful ``internet_search`` :class:`ToolResult`.

    The tool's payload is a JSON string ``{"query": ..., "results": [{title, url, snippet}]}``.
    Returns the list of result dicts (only ``str`` fields kept), or ``[]`` on any malformed
    payload — the worker never trusts the shape.
    """
    try:
        payload: Any = json.loads(tool_result.content)
    except (json.JSONDecodeError, TypeError):
        return []
    raw = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    results: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": str(item.get("snippet", "")),
            }
        )
    return results


def _error_message(tool_result: ToolResult) -> str:
    """Pull the human-readable message out of an error :class:`ToolResult` (best effort)."""
    try:
        payload: Any = json.loads(tool_result.content)
    except (json.JSONDecodeError, TypeError):
        return "web search failed"
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return f"web search failed: {payload['error']}"
    return "web search failed"


async def _crawl_top_results(
    results: Sequence[dict[str, str]],
    http_client: httpx.AsyncClient | None,
    *,
    max_crawl: int,
    timeout: float,
) -> dict[str, str]:
    """Crawl up to ``max_crawl`` of the top result URLs, returning ``{url: extracted_text}``.

    Bounded fan-out (``max_crawl`` pages) and sequential — no unbounded concurrency. Manages a
    short-lived **SSRF-guarded** ``httpx.AsyncClient`` (:func:`build_guarded_client`, design
    §7.2) when none is injected; an injected client (tests) is assumed already guarded and left
    open for the caller to own. Each page fails soft.
    """
    targets = [r["url"] for r in results[:max_crawl] if r.get("url")]
    if not targets:
        return {}

    client = http_client or build_guarded_client(timeout=timeout)
    owns_client = http_client is None
    extracts: dict[str, str] = {}
    try:
        for url in targets:
            text = await _crawl_page(client, url, timeout=timeout)
            if text:
                extracts[url] = text
    finally:
        if owns_client:
            await client.aclose()
    return extracts


async def _crawl_page(client: httpx.AsyncClient, url: str, *, timeout: float) -> str | None:
    """Fetch one page and return its bounded plain-text extract, or ``None`` on any failure.

    Bounded on every axis: a capped timeout; redirects followed **through the SSRF guard**
    (:class:`~app.net.ssrf_guard.GuardedTransport` re-validates every hop, design §7.2); only
    ``text/html`` bodies read; at most :data:`CRAWL_MAX_BYTES` streamed into memory (via
    :func:`~app.net.ssrf_guard.read_capped`); and the extracted text trimmed to
    :data:`EXTRACT_MAX_CHARS`. Any error — timeout, HTTP status, transport, decode, or an
    :class:`~app.net.ssrf_guard.SsrfError` raised by the guard for a private/blocked target —
    is caught and logged as a per-URL fail-soft skip; a single untrusted page (or a page that
    redirects somewhere unsafe) must never crash the worker.
    """
    try:
        async with client.stream("GET", url, timeout=timeout) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower():
                return None
            raw = await read_capped(response, max_bytes=CRAWL_MAX_BYTES)
            encoding = response.charset_encoding or "utf-8"
    except Exception as exc:
        # Untrusted-page crawl: any failure is per-URL fail-soft, never fatal to the worker.
        logger.warning("web crawl failed for %s: %s", url, exc)
        return None

    text = html_to_text(raw.decode(encoding, errors="replace"))
    return _truncate(text, EXTRACT_MAX_CHARS) or None


def _to_citation(result: Mapping[str, str]) -> Citation:
    """Map one search result to a :class:`Citation` (design §3 provenance)."""
    return Citation(
        title=result.get("title") or None,
        url=result.get("url") or None,
        snippet=_truncate(result.get("snippet", ""), SNIPPET_MAX_CHARS) or None,
        worker=WorkerName.WEB_SEARCH,
    )


def _bundle(results: Sequence[dict[str, str]], extracts: Mapping[str, str]) -> str:
    """Concatenate the results into one numbered grounding bundle for the responder.

    Each entry uses the crawled excerpt when available, otherwise the search snippet — inert
    text the responder can reference as ``[1]``, ``[2]`` … alongside the parallel citation
    list. This is grounding material, **not** a composed answer.
    """
    lines: list[str] = []
    for i, r in enumerate(results, start=1):
        url = r.get("url", "")
        title = r.get("title") or "Untitled source"
        body = extracts.get(url) or r.get("snippet", "")
        lines.append(f"[{i}] {title} ({url}): {body}".rstrip())
    return "\n\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars on a whitespace-friendly boundary with an ellipsis."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
