"""Celery task + CLI to mine the learning-resource corpus into the shared KB (P6-06).

The thin production wiring around
:func:`app.ingestion.learning_resources.discover_learning_resources` (which owns the logic).
Mining is an **expensive, uncached** job — Tavily search → crawl course
pages → LLM normalization → embed + upsert shared ``kb_documents`` — so it runs **only** as a
Celery task, **never** on a user-facing request path (design §5.7 / §7.5: *"never let a
user-facing turn trigger uncached crawling"*). A later PDP (P7) only *reads* the cached result.

Resources are discovered once and **amortized** across every user with that skill gap (§5.7), so
the task is keyed on a list of ``skills`` strings, never on a user. Two entry points, same core:

* :func:`mine_learning_resources_task` — the Celery task (``bind=True``, Redis-backed progress
  via ``update_state``), triggered on-demand or by a periodic TTL-refresh sweep (§5.7).
* :func:`main` / ``python -m app.tasks.learning_resources --skill Kubernetes --skill Python`` — a
  thin CLI that runs the mine **in-process** (no broker) for a one-off run.

Like :mod:`app.tasks.market` / :mod:`app.tasks.taxonomy`, the worker builds its own collaborators
(embedder + Postgres provider + Redis-backed LLM router + Tavily search pool) — a Celery worker
does not share the FastAPI ``app.state`` — and disposes them when done. Heavy imports are deferred
so importing this module (for the Celery ``include`` list) stays light and needs no ML stack.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from app.config import settings
from app.ingestion.learning_resources import discover_learning_resources
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)


async def _mine_entrypoint(
    *,
    skills: Sequence[str],
    progress: Callable[[str, dict[str, Any]], None] = lambda _s, _m: None,
) -> dict[str, Any]:
    """Build the worker-local collaborators, run the mine, and release resources.

    The standalone-worker composition root for learning-resource mining: constructs its own
    embedder, Postgres provider, Redis-backed LLM router (the normalizer), and Tavily search pool
    here (heavy imports deferred to keep module import light), and disposes the Postgres pool +
    Redis client when the run ends. The SSRF-guarded crawl client is owned per-run by the pipeline
    itself (default), so nothing extra is wired here.
    """
    from redis.asyncio import Redis  # noqa: PLC0415 - deferred worker-only dependency

    from app.llm.embeddings import SentenceTransformerEmbeddingClient  # noqa: PLC0415
    from app.llm.router import LLMRouter, RedisLike  # noqa: PLC0415
    from app.repositories.postgres import PostgresConnectionProvider  # noqa: PLC0415
    from app.tools.internet_search import InternetSearchTool  # noqa: PLC0415

    redis_client: Redis | None = None
    db: PostgresConnectionProvider | None = None
    try:
        redis_client = Redis.from_url(settings.REDIS_URL)
        redis_like = cast("RedisLike", redis_client)
        router = LLMRouter.from_settings(settings, redis_client=redis_like)
        search = InternetSearchTool.from_settings(settings, redis_client=redis_like)
        embedder = SentenceTransformerEmbeddingClient()
        db = PostgresConnectionProvider.from_settings()
        return await discover_learning_resources(
            skills,
            embedder=embedder,
            db=db,
            search=search,
            extractor=router,
            progress=progress,
        )
    finally:
        if db is not None:
            await db.aclose()
        if redis_client is not None:
            await redis_client.aclose()


@celery_app.task(bind=True, name="tasks.mine_learning_resources")
def mine_learning_resources_task(self: Any, *, skills: list[str]) -> dict[str, Any]:
    """Celery entry: mine + persist learning resources for ``skills`` into the shared KB (§5.7).

    Sync task body bridging to the async pipeline via :func:`asyncio.run`, reporting progress
    through Celery's own Redis-backed state machinery. An unrecoverable error propagates so
    Celery records ``FAILURE`` with the message.
    """

    def progress(state: str, meta: dict[str, Any]) -> None:
        self.update_state(state=state, meta=dict(meta))

    try:
        return asyncio.run(_mine_entrypoint(skills=skills, progress=progress))
    except Exception:
        logger.warning("Learning-resource mining task failed for skills %r", skills, exc_info=True)
        raise


def main(argv: list[str] | None = None) -> int:
    """CLI: run the learning-resource mine in-process (no broker).

    ``python -m app.tasks.learning_resources --skill Kubernetes --skill "Prompt Engineering"``.
    """
    parser = argparse.ArgumentParser(
        description="Mine learning resources for one or more skills into the shared KB."
    )
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        required=True,
        help="A skill to find learning resources for (repeatable).",
    )
    args = parser.parse_args(argv)

    def progress(state: str, meta: dict[str, Any]) -> None:
        print(f"[{state}] {meta.get('message', '')}")

    result = asyncio.run(_mine_entrypoint(skills=args.skills, progress=progress))
    print(
        f"Mined {result['resources_discovered']} learning resource(s) "
        f"for {result['skills_requested']} skill(s): "
        f"{result['documents_written']} documents, {result['chunks_written']} chunks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
