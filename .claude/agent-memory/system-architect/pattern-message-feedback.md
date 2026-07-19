---
name: pattern-message-feedback
description: P9-01 message_feedback capture blessed pattern — store-level ownership, one-row-per-message upsert, read seams for P9-03 learn step
metadata:
  type: project
---

P9-01 (message_feedback capture, `POST /api/messages/{message_id}/feedback`) APPROVED rev 1.

Blessed pattern for the P9 teachable-memory feedback loop:
- **Port** `MessageFeedbackStore` (ABC) in `services/`, **PG adapter** `PostgresMessageFeedbackStore` in `repositories/`, router in `api/message_feedback.py` — mirrors `ProfileStore`/`FeedbackReader`.
- **Ownership enforced in the store, not the router**: `record()` resolves owner via `messages`→`conversations` join, returns `None` for unknown *or* not-owned; router maps single `None` → uniform 404 (no missing-vs-not-yours leak, same as `dashboard.py`). This realizes the repo-level owner-filter follow-up logged in [[project-authz-ratelimit]].
- Logged-in matched by `user_id` (so cross-session feedback resolves), guest by `session_id`. Identity from `require_auth`/`CurrentUser`, never the body.
- **One row per message**: `UNIQUE(message_id)` (migration 0009, dropped redundant `ix_`), `ON CONFLICT (message_id) DO UPDATE` restamps `created_at`. Persist the *message's* owning ids (not caller's fresh/Redis-only session) to satisfy the `sessions` FK.
- Read seams `get_for_message` + `list_recent_downvotes(user_id, limit)` are the contract P9-03 (LangMem learn/demote) consumes — it reads *latest* rating, not full history.

**Why:** capture-only per scope; P9-03 (learn/demote) and P9-09 (frontend widget) are separate.
**How to apply:** for P9-03, expect it to call `list_recent_downvotes`; don't let it re-implement ownership or reach into the table directly.
