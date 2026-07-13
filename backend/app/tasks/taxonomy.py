"""Celery task + CLI to seed the shared KB with the ESCO/O*NET taxonomy subset (P6-01).

The thin production wiring around :mod:`app.ingestion.taxonomy_seed` (which owns the logic).
This is a **one-time / occasional** seed, not a per-request path: it loads the bundled static
fixture, embeds each occupation with the in-process :class:`EmbeddingClient`, and idempotently
upserts shared ``kb_documents`` (``user_id IS NULL``, ``source_type='curated'``) + ``kb_chunks``.
Re-running is safe (upsert keyed on ``source = "<taxonomy>:<id>"`` — no duplicate rows).

Two entry points, same core:

* :func:`seed_taxonomy_task` — the Celery task (``bind=True``, Redis-backed progress via
  ``update_state``), so it can be triggered on-demand on the worker.
* :func:`main` / ``python -m app.tasks.taxonomy`` — a thin CLI that runs the seed **in-process**
  (no broker needed) for a one-off run, printing the result summary. Optional ``--path`` points
  at an alternate fixture (the documented upgrade path in ``app/ingestion/data/README.md``).

Like :mod:`app.tasks.profile_ingest`, the worker builds its own collaborators (embedder +
Postgres provider) — a Celery worker does not share the FastAPI ``app.state`` composition root —
and disposes the pool when done. Heavy imports are deferred so importing this module (e.g. by the
Celery ``include`` list) stays light and needs no ML stack.

**No scraping / no live external HTTP** happens anywhere here: the data is the checked-in
fixture read from disk.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.ingestion.taxonomy_seed import (
    DEFAULT_SEED_PATH,
    load_seed_occupations,
    run_taxonomy_seed,
)
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


async def _seed_entrypoint(
    *,
    path: Path | str,
    progress: Callable[[str, dict[str, Any]], None] = lambda _state, _meta: None,
) -> dict[str, Any]:
    """Build the worker-local collaborators, run the seed, and release the DB pool.

    The standalone-worker composition root for the taxonomy seed: constructs its own embedder +
    Postgres provider here (heavy imports deferred to keep module import light) and disposes the
    pool when the run ends — the worker does not share the FastAPI ``app.state``.
    """
    from app.llm.embeddings import SentenceTransformerEmbeddingClient  # noqa: PLC0415
    from app.repositories.postgres import PostgresConnectionProvider  # noqa: PLC0415

    occupations = load_seed_occupations(path)
    db = PostgresConnectionProvider.from_settings()
    try:
        embedder = SentenceTransformerEmbeddingClient()
        return await run_taxonomy_seed(
            occupations=occupations, embedder=embedder, db=db, progress=progress
        )
    finally:
        await db.aclose()


@celery_app.task(bind=True, name="tasks.seed_taxonomy")
def seed_taxonomy_task(self: Any, *, path: str | None = None) -> dict[str, Any]:
    """Celery entry: seed the shared KB from the bundled taxonomy fixture (idempotent).

    Sync task body bridging to the async pipeline via :func:`asyncio.run`, reporting progress
    through Celery's own Redis-backed state machinery. ``path`` defaults to the bundled fixture;
    pass an alternate to ingest a swapped-in dataset (see the module docstring / data README).
    An unrecoverable error propagates so Celery records ``FAILURE`` with the message.
    """
    seed_path = path or str(DEFAULT_SEED_PATH)

    def progress(state: str, meta: dict[str, Any]) -> None:
        self.update_state(state=state, meta=dict(meta))

    try:
        return asyncio.run(_seed_entrypoint(path=seed_path, progress=progress))
    except Exception:
        logger.warning("Taxonomy seed task failed for path %s", seed_path, exc_info=True)
        raise


def main(argv: list[str] | None = None) -> int:
    """CLI: run the taxonomy seed in-process (no broker). ``python -m app.tasks.taxonomy``.

    Runs the same core as the Celery task directly against Postgres, for a one-off/manual seed.
    Prints the result summary and returns a process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(
        description="Seed the shared KB with the ESCO/O*NET taxonomy subset."
    )
    parser.add_argument(
        "--path",
        default=str(DEFAULT_SEED_PATH),
        help="Path to the seed fixture JSON (defaults to the bundled subset).",
    )
    args = parser.parse_args(argv)

    def progress(state: str, meta: dict[str, Any]) -> None:
        print(f"[{state}] {meta.get('message', '')}")

    result = asyncio.run(_seed_entrypoint(path=args.path, progress=progress))
    print(
        "Seeded taxonomy: "
        f"{result['documents_written']} documents, {result['chunks_written']} chunks "
        f"from {result['occupations']} occupations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
