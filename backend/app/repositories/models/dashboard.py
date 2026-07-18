"""PDP & dashboard ("living PDP") ORM models (design §4 / §5.2 — relational + JSONB).

Part of the third real table group of the v2 schema (P2-05, *structured records*). Every
class subclasses the shared :class:`~app.repositories.postgres.Base` so it lands on the one
``metadata`` Alembic autogenerates from and the repository layer queries through.

Tables (§4 "Dashboard (living PDP)" + §5.2):

* :class:`Pdp` — a generated PDP record (§4). No object storage exists yet, so it stores
  enough to *regenerate* the styled PDF on demand (``career_goal``, ``target_date``, the
  structured ``content`` sections v1 rendered); ``pdf_path`` is a nullable pointer for a
  future object-storage integration.
* :class:`Goal` → :class:`Milestone` → :class:`DashboardTask` — the goal/milestone/task
  hierarchy the user edits and the AI can read/propose/update.
* :class:`ProgressEntry` — an **append-only** log of progress/notes/check-ins for
  trend/streak views. *No update path* is modeled (no ``updated_at``) — appends only.

Design constraints baked into the schema here:

* **Attribution: ``source`` (``user`` | ``ai``) — §5.2.** §5.2 requires *"every change is
  attributable (source = user|ai)"* and that AI writes are *"explicit, confirmable changes
  (proposed → user approves) rather than silent mutations."* This task is schema-only (no
  dashboard tools yet), but the schema must not preclude that workflow, so **every mutable
  dashboard entity** (goals, milestones, tasks, progress_entries) carries a checked
  ``source`` column. In addition, each ``status`` vocabulary **already includes
  ``'proposed'``** — the pending-approval state an AI-proposed row starts in — so the future
  "proposed-by-ai → user approves" feature needs *no schema migration* to introduce it (a
  dedicated ``approved_at`` column, if wanted, can be a later feature-scoped migration).
* **Checked varchar, not native ``ENUM``.** ``status`` / ``source`` use ``String`` +
  ``CheckConstraint`` (matching the ``role`` / ``rating`` / ``memory_type`` / ``source_type``
  posture from P2-03/04): adding a value later is a cheap check-constraint swap, not a
  fragile ``ALTER TYPE``.
* **``tasks.milestone_id`` is optional; ``tasks.goal_id`` is required.** §5.2 nests tasks
  under milestones under goals, but a task can exist directly under a goal before any
  milestone is set ("no milestone yet"). So every task is anchored to a goal (``goal_id``
  NOT NULL, cascade) and *optionally* to a milestone (``milestone_id`` nullable). Deleting a
  milestone ``SET NULL``s its tasks' ``milestone_id`` (they fall back to the goal, surviving)
  rather than deleting them; deleting the goal removes the tasks via the ``goal_id`` cascade.
* **GDPR-delete + cascade posture (§4).** Deleting a user cascades to their PDPs, goals
  (→ milestones → tasks) and progress_entries. Within the dashboard, deleting a goal cascades
  to its milestones and tasks. ``progress_entries.goal_id`` / ``.task_id`` are ``SET NULL``
  (not cascade): the append-only log is user-scoped history and should survive the user
  editing their plan — only a user-delete (via ``user_id`` cascade) erases it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.repositories.models._mixins import CreatedAtMixin
from app.repositories.postgres import Base

#: Attribution of a dashboard write (§5.2: "source = user|ai"). Present on every mutable
#: dashboard entity so a future AI-proposal workflow is attributable.
_SOURCE_VALUES = ("user", "ai")
#: Goal lifecycle. ``proposed`` is the pending-approval state for AI-proposed goals (§5.2),
#: included now so that workflow needs no later migration.
_GOAL_STATUS_VALUES = ("proposed", "active", "completed", "abandoned")
#: Milestone lifecycle (``proposed`` = AI-proposed, pending user approval).
_MILESTONE_STATUS_VALUES = ("proposed", "pending", "in_progress", "completed")
#: Task lifecycle (``proposed`` = AI-proposed, pending user approval).
_TASK_STATUS_VALUES = ("proposed", "todo", "in_progress", "done", "cancelled")


class Pdp(CreatedAtMixin, Base):
    """A generated Personal Development Plan record (§4).

    Stores enough to *regenerate* the styled PDF on demand (no object storage yet):
    ``career_goal`` + ``target_date`` + the structured ``content`` sections. ``pdf_path`` is
    a nullable pointer reserved for a future object-storage integration.
    """

    __tablename__ = "pdps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    career_goal: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Structured PDP sections (the ## headings v1 generated) as JSONB — enough to
    # re-render the PDF without object storage.
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Nullable future object-storage pointer (no object storage wired yet).
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class Goal(CreatedAtMixin, Base):
    """A user career goal (§5.2) — the root of the goal → milestone → task hierarchy."""

    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in _GOAL_STATUS_VALUES)})",
            name="ck_goals_status",
        ),
        CheckConstraint(
            f"source IN ({', '.join(repr(v) for v in _SOURCE_VALUES)})",
            name="ck_goals_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    target_role: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="user")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    milestones: Mapped[list[Milestone]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[DashboardTask]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class Milestone(CreatedAtMixin, Base):
    """A checkpoint under a :class:`Goal` (§5.2)."""

    __tablename__ = "milestones"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in _MILESTONE_STATUS_VALUES)})",
            name="ck_milestones_status",
        ),
        CheckConstraint(
            f"source IN ({', '.join(repr(v) for v in _SOURCE_VALUES)})",
            name="ck_milestones_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="user")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    goal: Mapped[Goal] = relationship(back_populates="milestones")
    tasks: Mapped[list[DashboardTask]] = relationship(back_populates="milestone")


class DashboardTask(CreatedAtMixin, Base):
    """An actionable dashboard item (§5.2).

    Named ``DashboardTask`` (table ``tasks``) to keep it **unambiguously distinct** from the
    Celery task modules in ``app/tasks/`` — this is a persisted dashboard row, not a
    background job. Anchored to a :class:`Goal` (required) and optionally to a
    :class:`Milestone` (nullable — a task can exist before any milestone). Carries
    ``source`` (``user`` | ``ai``) for §5.2 attribution.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in _TASK_STATUS_VALUES)})",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            f"source IN ({', '.join(repr(v) for v in _SOURCE_VALUES)})",
            name="ck_tasks_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Required anchor: every task belongs to a goal (cascade on goal-delete).
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional: a task may have no milestone yet. SET NULL so deleting a milestone detaches
    # its tasks (they survive under the goal) rather than deleting them.
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("milestones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="todo")
    # §5.2: "every change is attributable (source = user|ai)".
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="user")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    goal: Mapped[Goal] = relationship(back_populates="tasks")
    milestone: Mapped[Milestone | None] = relationship(back_populates="tasks")


class ProgressEntry(CreatedAtMixin, Base):
    """An **append-only** progress/notes/check-in log entry (§5.2 — trend/streak views).

    Deliberately has **no ``updated_at``** and no update path: entries are only ever
    appended, never mutated — the log *is* the history. User-scoped (cascade on user-delete);
    the optional ``goal_id`` / ``task_id`` are ``SET NULL`` so the log survives the user
    editing/deleting the plan it refers to.
    """

    __tablename__ = "progress_entries"
    __table_args__ = (
        CheckConstraint(
            f"source IN ({', '.join(repr(v) for v in _SOURCE_VALUES)})",
            name="ck_progress_entries_source",
        ),
        # Streak / trend views (§5.2) scan a user's log ordered by time: filter by
        # ``user_id`` and group/order by ``created_at``. A composite ``(user_id,
        # created_at)`` index serves that directly; because ``user_id`` is the leading
        # column it also covers the plain per-user FK lookup, so no separate
        # single-column ``user_id`` index is kept (it would be redundant).
        Index("ix_progress_entries_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Optional references — SET NULL so the append-only log outlives plan edits.
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Attribution (§5.2) — a progress entry may be logged by the user or the AI.
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="user")
