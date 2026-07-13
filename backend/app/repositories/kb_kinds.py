"""Single source of truth for the shared-KB ``meta["kind"]`` markers (design §5.6 / §5.7).

The shared corpus (``kb_documents`` with ``user_id IS NULL`` and ``source_type='curated'``)
holds **three** distinct producers that all carry the same ``source_type`` and can only be told
apart by their ``meta["kind"]``:

* **taxonomy occupations** (P6-01 seed) — the role-canonicalization baseline,
* **mined role-profile summaries** (P6-04) — the ``"Market requirements: <role>"`` documents,
* **learning resources** (P6-06) — courses / tracks / certifications.

``market_agent._resolve_baseline`` must match a *taxonomy occupation* (not a role-profile
summary that happens to out-rank it, nor a learning resource), so every producer stamps its
kind and every consumer imports these constants from **here** — the three string literals must
not drift across ``ingestion/`` and ``agents/``. This module has no heavy imports, so both
``ingestion/`` and ``agents/`` can depend on it without an import cycle.
"""

from __future__ import annotations

__all__ = ["LEARNING_RESOURCE_KIND", "ROLE_PROFILE_KIND", "TAXONOMY_KIND"]

#: A taxonomy occupation document (P6-01 seed) — the role-canonicalization baseline.
TAXONOMY_KIND = "taxonomy_occupation"

#: A mined role-profile summary document (P6-04) — ``"Market requirements: <role>"``.
ROLE_PROFILE_KIND = "role_profile"

#: A learning-resource document (P6-06) — a course / track / certification.
LEARNING_RESOURCE_KIND = "learning_resource"
