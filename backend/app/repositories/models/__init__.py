# ORM models — SQLAlchemy 2.x mapped classes on the shared ``Base`` (design §4/§8).
#
# One subpackage under ``repositories/`` holds every table group so they all
# register on the single ``Base.metadata`` that Alembic autogenerates from and the
# app's repositories query through. Importing this package imports every model
# module, which is what populates ``Base.metadata`` — so ``migrations/env.py`` and
# tests only need ``import app.repositories.models`` to see the full schema.
#
# Table groups (added phase-by-phase, same convention each time):
#   * identity / conversation / documents         → P2-03
#   * knowledge base / memories                    → P2-04
#   * structured records: jobs, PDPs, dashboard    → P2-05

from app.repositories.models.dashboard import (
    DashboardTask,
    Goal,
    Milestone,
    Pdp,
    ProgressEntry,
)
from app.repositories.models.identity import (
    Conversation,
    Feedback,
    Message,
    MessageFeedback,
    Preference,
    Profile,
    Session,
    User,
)
from app.repositories.models.jobs import (
    Job,
)
from app.repositories.models.knowledge import (
    KbChunk,
    KbDocument,
    UserMemory,
)

__all__ = [
    "Conversation",
    "DashboardTask",
    "Feedback",
    "Goal",
    "Job",
    "KbChunk",
    "KbDocument",
    "Message",
    "MessageFeedback",
    "Milestone",
    "Pdp",
    "Preference",
    "Profile",
    "ProgressEntry",
    "Session",
    "User",
    "UserMemory",
]
