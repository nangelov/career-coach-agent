"""Persistence seam for generated PDPs (Postgres-backed in :mod:`app.repositories.pdp_store`).

``POST /api/pdp`` (P7-03) persists every generated Personal Development Plan as a first-class
``pdps`` row (P2-05 schema) so a PDP is a stored record — regenerable on demand and ready for
P8's dashboard-seeding to read — not a fire-and-forget download. That need is exactly one
capability against the ``pdps`` table: insert a new plan for a user. It gets a narrow port here,
following the interface-before-implementation idiom the codebase uses (``ProfileStore``,
``UserStore``, …): this module defines the port plus a process-local implementation for tests;
the **Postgres-backed** adapter (:class:`~app.repositories.pdp_store.PostgresPdpStore`) lives in
the repository layer.

The port trades in the typed :class:`~app.schemas.pdp.PdpContent` (the structured six-section
plan the P7-01 agent produced) — the adapter dumps it into the ``pdps.content`` JSONB column, so
one source of truth for a plan's shape spans the agent, the PDF builder and the stored row.

User-scoped by construction (§7 AuthZ): every write keys on the caller's ``users.id`` (the
verified token subject), so there is no path/body ``user_id`` a caller could point at another
user — a PDP is always anchored to its owner's row (the ``pdps.user_id`` FK).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from app.schemas.pdp import PdpContent


class PdpStore(ABC):
    """Persist a generated PDP as a ``pdps`` row (§4 — one row per generation, append-only).

    Implementations own storage (process-local here, Postgres in the repository layer); the
    PDP service depends only on this interface. All writes are keyed on ``users.id`` — the store
    never exposes a way to write against another user's row.
    """

    @abstractmethod
    async def save(
        self,
        *,
        user_id: str,
        career_goal: str,
        target_date: date | None,
        content: PdpContent,
    ) -> str:
        """Insert a new PDP row for ``user_id`` and return its generated id.

        Each call creates a **new** row (a PDP is a point-in-time record — "regenerate on
        demand" appends a fresh row rather than mutating the last one), storing enough to
        re-render the styled PDF without object storage: the ``career_goal``, ``target_date``
        and the structured ``content`` sections (as ``pdps.content`` JSONB).
        """


@dataclass(frozen=True)
class StoredPdp:
    """One persisted PDP recorded by :class:`InMemoryPdpStore` (test-double bookkeeping)."""

    id: str
    user_id: str
    career_goal: str
    target_date: date | None
    content: PdpContent


class InMemoryPdpStore(PdpStore):
    """Process-local :class:`PdpStore` — test double only.

    Records every saved PDP in insertion order (:attr:`saved`) so a test can assert a row is
    persisted per generation and inspect what was stored, without a real Postgres. Not for
    production.
    """

    def __init__(self) -> None:
        self.saved: list[StoredPdp] = []

    async def save(
        self,
        *,
        user_id: str,
        career_goal: str,
        target_date: date | None,
        content: PdpContent,
    ) -> str:
        pdp_id = uuid.uuid4().hex
        self.saved.append(
            StoredPdp(
                id=pdp_id,
                user_id=user_id,
                career_goal=career_goal,
                target_date=target_date,
                content=content,
            )
        )
        return pdp_id
