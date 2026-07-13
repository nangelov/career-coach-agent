"""Account-scoped GDPR request/response models — erasure + export (§7.6 / §9).

The one authoritative contract for the ``/api/me`` surface (SEC-05):

* :class:`AccountExport` — the Art. 20 *portability* document ``GET /api/me/export`` returns:
  every row the caller owns, grouped by store, in one JSON payload. Each section is a list of
  already-JSON-safe row dicts (UUIDs stringified, timestamps ISO-formatted by the repository
  layer) so the shape stays flat and stable for a downloaded file, rather than forcing a typed
  model per table. Two design constraints are baked in here and enforced in the repository:

  - **Raw embedding vectors are excluded.** ``kb_chunks`` / ``user_memories`` carry a
    ``vector(4096)`` embedding column; it is a derived artifact (not user-supplied data) and a
    4096-float array per row would bloat the export pointlessly. The repository never selects
    those columns, so they cannot leak into this document.
  - **Strictly caller-scoped.** Every section is filtered to ``user_id = caller`` (or joined
    through an owned parent); shared/curated KB rows (``user_id IS NULL``) and any other user's
    rows are never included.

There is no request model for ``DELETE /api/me``: the target is always the verified token
subject (no body, no path/query ``user_id`` a caller could point at another account, §7 AuthZ).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: A single exported row as a JSON-safe mapping (UUID/date/datetime already coerced to strings
#: by the repository). Kept as an open mapping rather than a typed model per table: the export
#: is a portability dump, not an API the frontend renders field-by-field.
ExportRow = dict[str, Any]


class AccountExport(BaseModel):
    """A complete, caller-scoped export of one user's data (GDPR Art. 20, §7.6).

    Every field is the user's **own** data only. Single-row stores (``user`` / ``profile`` /
    ``preferences``) are ``None`` when absent; multi-row stores default to an empty list. Raw
    embedding vectors are intentionally absent (see the module docstring).
    """

    user: ExportRow | None = Field(default=None, description="The user account row (§4 users).")
    profile: ExportRow | None = Field(
        default=None, description="Structured CV/profile document (§4 profiles)."
    )
    preferences: ExportRow | None = Field(
        default=None, description="Explicit personalization settings (§4 preferences)."
    )
    conversations: list[ExportRow] = Field(default_factory=list)
    messages: list[ExportRow] = Field(default_factory=list)
    message_feedback: list[ExportRow] = Field(default_factory=list)
    feedback: list[ExportRow] = Field(default_factory=list)
    kb_documents: list[ExportRow] = Field(
        default_factory=list, description="The user's own (CV-derived) KB documents only."
    )
    kb_chunks: list[ExportRow] = Field(
        default_factory=list, description="Chunks of the user's own documents — no raw embeddings."
    )
    user_memories: list[ExportRow] = Field(
        default_factory=list, description="Learned per-user memories — no raw embeddings."
    )
    pdps: list[ExportRow] = Field(default_factory=list)
    goals: list[ExportRow] = Field(default_factory=list)
    milestones: list[ExportRow] = Field(default_factory=list)
    tasks: list[ExportRow] = Field(default_factory=list)
    progress_entries: list[ExportRow] = Field(default_factory=list)
