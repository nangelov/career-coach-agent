"""Celery post-turn learn task — extract/dedupe/confidence + thumb-down demotion (§5.4 / §5.5).

The producer side of the teachable-memory *learn* loop. After a logged-in user's turn completes,
:class:`~app.services.chat.ChatService` enqueues :func:`learn_from_turn`; this worker task then
runs the extraction + dedup + confidence + thumb-down pass off the request path (§5.4 point 3:
*"Learn (post-turn, async via Celery)"*) via the injectable core
:func:`app.memory.learn.run_learn_from_turn`.

**Sync task, async stack — the bridge (mirrors :mod:`app.tasks.profile_ingest`).** Celery tasks
are synchronous but the DB/embedding/LLM stack is async-only, so the task wraps an async
implementation in :func:`asyncio.run`. It constructs its **own** embedder / LLM router / Postgres
provider / feedback store **inside the worker process** (a worker does not share the FastAPI
``app.state`` composition root) and closes them when the task ends. Heavy imports are deferred into
the builder so importing this module (e.g. by the API composition root, for
:func:`enqueue_learn_from_turn`) stays light and needs no ML stack.

**Guest handling.** Guests have no ``users`` row and no durable memory (§5.4), so the enqueue point
never fires for them; the core also returns a ``skipped`` result for a missing/malformed user id
as belt-and-braces.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from app.config import settings
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from app.memory.learn import LearnConfig, MemoryExtractor, TurnFeedbackReader
    from app.memory.store import UserMemoryStore

logger = logging.getLogger(__name__)


async def run_memory_learn(
    *,
    user_id: str,
    message_id: str,
    user_text: str,
    assistant_text: str,
    store: UserMemoryStore,
    extractor: MemoryExtractor,
    feedback: TurnFeedbackReader,
    config: LearnConfig | None = None,
) -> dict[str, Any]:
    """Run the learn pass over injected collaborators; return the JSON-serializable summary.

    A thin adapter over :func:`app.memory.learn.run_learn_from_turn` returning ``.summary()`` (the
    Celery result). Kept separate from the task body so tests can drive the full production wiring
    with fakes and no broker.
    """
    from app.memory.learn import run_learn_from_turn  # noqa: PLC0415 - keep module import light

    result = await run_learn_from_turn(
        user_id=user_id,
        message_id=message_id,
        user_text=user_text,
        assistant_text=assistant_text,
        store=store,
        extractor=extractor,
        feedback=feedback,
        config=config,
    )
    return result.summary()


async def _learn_entrypoint(
    *,
    user_id: str,
    message_id: str,
    user_text: str,
    assistant_text: str,
) -> dict[str, Any]:
    """Build the worker-local collaborators, run the learn pass, and release resources.

    The standalone-worker composition root for the learn task: constructs its own embedder / LLM
    router / Postgres provider / feedback store (heavy imports deferred), and disposes the Postgres
    pool and Redis client when the task ends.
    """
    from redis.asyncio import Redis  # noqa: PLC0415 - deferred worker-only dependency

    from app.llm.embeddings import SentenceTransformerEmbeddingClient  # noqa: PLC0415
    from app.llm.router import LLMRouter, RedisLike  # noqa: PLC0415
    from app.memory.learn import LLMMemoryExtractor  # noqa: PLC0415
    from app.memory.store import UserMemoryStore  # noqa: PLC0415
    from app.repositories.message_feedback_store import (  # noqa: PLC0415
        PostgresMessageFeedbackStore,
    )
    from app.repositories.postgres import PostgresConnectionProvider  # noqa: PLC0415

    redis_client: Redis | None = None
    db: PostgresConnectionProvider | None = None
    try:
        redis_client = Redis.from_url(settings.REDIS_URL)
        router = LLMRouter.from_settings(settings, redis_client=cast("RedisLike", redis_client))
        db = PostgresConnectionProvider.from_settings()
        store = UserMemoryStore(embedder=SentenceTransformerEmbeddingClient(), db=db)
        feedback = PostgresMessageFeedbackStore.from_provider(db)
        return await run_memory_learn(
            user_id=user_id,
            message_id=message_id,
            user_text=user_text,
            assistant_text=assistant_text,
            store=store,
            extractor=LLMMemoryExtractor(router),
            feedback=feedback,
        )
    finally:
        if db is not None:
            await db.aclose()
        if redis_client is not None:
            await redis_client.aclose()


@celery_app.task(bind=True, name="tasks.learn_from_turn")
def learn_from_turn(
    self: Any,
    *,
    user_id: str,
    message_id: str,
    user_text: str,
    assistant_text: str,
) -> dict[str, Any]:
    """Celery entry: learn durable memories from one completed turn (§5.4 point 3).

    Sync task body: bridges to the async learn pass via :func:`asyncio.run`. A failure propagates
    so Celery records ``FAILURE`` (learning is best-effort and off the request path, so this never
    affects the user's already-delivered answer) — logged for the worker operator.
    """
    try:
        return asyncio.run(
            _learn_entrypoint(
                user_id=user_id,
                message_id=message_id,
                user_text=user_text,
                assistant_text=assistant_text,
            )
        )
    except Exception:
        logger.warning("post-turn learn task failed for message %s", message_id, exc_info=True)
        raise


def enqueue_learn_from_turn(
    *,
    user_id: str,
    message_id: str,
    user_text: str,
    assistant_text: str,
) -> str:
    """Enqueue :func:`learn_from_turn` on the broker; return the task id.

    The production :class:`~app.services.chat.LearnEnqueuer` the composition root wires into
    :class:`~app.services.chat.ChatService`. A plain function (not a method) so the service depends
    only on the narrow callable port, never on Celery.
    """
    async_result = learn_from_turn.apply_async(
        kwargs={
            "user_id": user_id,
            "message_id": message_id,
            "user_text": user_text,
            "assistant_text": assistant_text,
        }
    )
    return str(async_result.id)
