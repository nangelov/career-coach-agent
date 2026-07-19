"""Memory-panel API contract — explicit preferences + learned memories (P9-05, §5.4).

The typed request/response shapes the thin ``/api/memory`` router trades in and the
:class:`~app.services.memory.MemoryService` returns. This is the *transparency & control*
surface (§5.4 point 4 / §6.10 — learned memory is silent-but-viewable/deletable): the user
views/edits their **explicit** :class:`Preferences` and views/deletes their **inferred**
:class:`LearnedMemory` rows. There is deliberately **no** per-fact confirmation workflow here
(§6.10) — edits and deletions are immediate.

Two boundary decisions are encoded here:

* **Preferences are a typed, bounded document** (not a free-form blob). The §5.4 fields
  (tone / formality / language / focus areas / do-not list) get named, length-capped fields so
  the write contract is explicit and abuse-bounded; unknown keys in a stored document are
  ignored on read (forward-compatible), mirroring how :class:`~app.ingestion.profile.ProfileSchema`
  is typed both ways. ``preferences`` remains the **authoritative** signal that overrides
  inferred memories (§5.4 point 4) — recall (P9-02) already injects it ahead of memories.
* **Embeddings never cross the wire.** :class:`LearnedMemory` carries only the display columns
  (id, text, type, confidence, created_at); the 4096-dim vector stays in the database (§7.6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

__all__ = [
    "ClearMemoriesResponse",
    "LearnedMemory",
    "MemoryView",
    "Preferences",
]

#: Abuse bounds for the free-text preference list fields (focus areas / do-not list).
_MAX_LIST_ITEMS = 50
_MAX_ITEM_LEN = 200

#: A length-capped free-text list item (bounds each entry, not just the list length).
_ListItem = Annotated[str, Field(max_length=_MAX_ITEM_LEN)]


class Preferences(BaseModel):
    """A user's explicit, editable personalization settings (§5.4) — the PUT body and response.

    All fields are optional so the panel can render/save a partial document; a ``PUT`` replaces
    the whole preferences document (upsert). Unknown keys in a stored document are ignored on
    read (pydantic default), so an older/other-sourced document degrades gracefully rather than
    raising.
    """

    tone: str | None = Field(
        default=None, max_length=64, description="Preferred coaching tone, e.g. 'encouraging'."
    )
    formality: str | None = Field(
        default=None, max_length=64, description="Preferred formality, e.g. 'casual'/'formal'."
    )
    language: str | None = Field(
        default=None, max_length=64, description="Preferred response language, e.g. 'en'."
    )
    focus_areas: list[_ListItem] = Field(
        default_factory=list,
        max_length=_MAX_LIST_ITEMS,
        description="Topics the coach should emphasise.",
    )
    avoid: list[_ListItem] = Field(
        default_factory=list,
        max_length=_MAX_LIST_ITEMS,
        description="The do-not list — topics/behaviours the coach should avoid.",
    )

    @classmethod
    def model_validate_lenient(cls, data: dict[str, object] | None) -> Preferences:
        """Validate a stored preferences document, tolerating a missing/empty row.

        ``None``/empty (no ``preferences`` row yet) yields an empty :class:`Preferences` so the
        panel always has a renderable shape — the friendlier read contract (mirrors the empty
        :class:`~app.ingestion.profile.ProfileSchema` fallback in the profile endpoint).
        """
        return cls.model_validate(data or {})


class LearnedMemory(BaseModel):
    """One inferred ``user_memories`` row as shown in the panel (embedding excluded, §7.6)."""

    id: str
    text: str
    memory_type: str
    confidence: float
    created_at: datetime


class MemoryView(BaseModel):
    """The ``GET /api/memory`` response — explicit preferences + the learned memories list."""

    preferences: Preferences
    memories: list[LearnedMemory] = Field(default_factory=list)


class ClearMemoriesResponse(BaseModel):
    """The ``DELETE /api/memory`` response — how many learned memories were cleared."""

    deleted: int
