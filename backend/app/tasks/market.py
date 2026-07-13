"""Celery task + CLI to mine market requirements for a role into the shared corpus (P6-04).

The thin production wiring around :func:`app.agents.market_agent.mine_role_requirements`
(which owns the logic). Mining is an **expensive, uncached** job — taxonomy match → crawl
recent postings → LLM requirement extraction → aggregate → upsert ``role_profiles`` + embed a
summary — so it runs **only** as a Celery task, **never** on a user-facing request path
(design §5.6 / §7.5: *"no user-facing turn triggers uncached crawling"*). A chat turn only
*reads* the cached result via the MARKET_INTEL worker.

Extraction is paid **once per role** and amortized across all users (§5.6), so the task is keyed
on a ``target_role`` string, never on a user. Two entry points, same core:

* :func:`mine_role_task` — the Celery task (``bind=True``, Redis-backed progress via
  ``update_state``), triggered on-demand or by a periodic refresh sweep (§5.6 TTL).
* :func:`main` / ``python -m app.tasks.market --role "AI Solution Architect"`` — a thin CLI that
  runs the mine **in-process** (no broker) for a one-off run.

Like :mod:`app.tasks.taxonomy` / :mod:`app.tasks.profile_ingest`, the worker builds its own
collaborators (embedder + Postgres provider + Redis-backed LLM router + search pool) — a Celery
worker does not share the FastAPI ``app.state`` — and disposes them when done. Heavy imports are
deferred so importing this module (for the Celery ``include`` list) stays light.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from app.agents.market_agent import mine_role_requirements
from app.config import settings
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


async def _mine_entrypoint(
    *,
    target_role: str,
    progress: Callable[[str, dict[str, Any]], None] = lambda _s, _m: None,
) -> dict[str, Any]:
    """Build the worker-local collaborators, run the mine, and release resources.

    The standalone-worker composition root for market mining: constructs its own embedder,
    Postgres provider, Redis-backed LLM router (the requirement extractor), and Tavily search
    pool here (heavy imports deferred to keep module import light), and disposes the Postgres
    pool + Redis client when the run ends. The SSRF-guarded crawl client is owned per-run by the
    pipeline itself (default), so nothing extra is wired here.
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
        return await mine_role_requirements(
            target_role,
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


@celery_app.task(bind=True, name="tasks.mine_role")
def mine_role_task(self: Any, *, target_role: str) -> dict[str, Any]:
    """Celery entry: mine + persist the market requirements for ``target_role`` (§5.6).

    Sync task body bridging to the async pipeline via :func:`asyncio.run`, reporting progress
    through Celery's own Redis-backed state machinery. An unrecoverable error propagates so
    Celery records ``FAILURE`` with the message.
    """

    def progress(state: str, meta: dict[str, Any]) -> None:
        self.update_state(state=state, meta=dict(meta))

    try:
        return asyncio.run(_mine_entrypoint(target_role=target_role, progress=progress))
    except Exception:
        logger.warning("Market mining task failed for role %r", target_role, exc_info=True)
        raise


def enqueue_mine_role(*, target_role: str) -> str:
    """Enqueue :func:`mine_role_task` on the broker; return the task id (P5-06 poll handle).

    The production enqueue port the composition root wires into
    :class:`~app.services.roles.RolesService`: on a cold ``GET /api/roles/{role}/requirements``
    (or ``/gap``) and on a stale-profile background refresh, the request path fires this and
    returns immediately — mining runs off the request path (§5.6 / §7.5, *"no user-facing turn
    triggers uncached crawling"*). Kept a plain function (not a method) so the service depends
    only on a narrow callable port, never on Celery. The returned id lets the client poll the
    existing ``GET /api/jobs/status/{task_id}`` (P5-06).
    """
    async_result = mine_role_task.apply_async(kwargs={"target_role": target_role})
    return str(async_result.id)


def main(argv: list[str] | None = None) -> int:
    """CLI: run the market mine in-process (no broker). ``python -m app.tasks.market``."""
    parser = argparse.ArgumentParser(
        description="Mine market requirements for a role into the shared corpus."
    )
    parser.add_argument(
        "--role", required=True, help="The target role to mine (e.g. 'Data Scientist')."
    )
    args = parser.parse_args(argv)

    def progress(state: str, meta: dict[str, Any]) -> None:
        print(f"[{state}] {meta.get('message', '')}")

    result = asyncio.run(_mine_entrypoint(target_role=args.role, progress=progress))
    print(
        f"Mined '{result['canonical_role']}': {result['postings_persisted']} postings, "
        f"{result['skill_count']} skills, {result['chunks_written']} summary chunks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
