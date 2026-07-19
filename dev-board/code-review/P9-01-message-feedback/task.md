# Task P9-01-message-feedback — message_feedback capture (👍/👎 + reason)
- **Phase:** P9   **Status:** ENG   **Tags:** (B)

## Scope
Implement `message_feedback` capture: `POST /api/messages/{message_id}/feedback` accepting a thumbs
up/down rating plus an optional free-text reason, persisted against the message (and the owning
conversation/user) in Postgres.

From `dev-board/tasks.md` (P9):
> `message_feedback` capture: 👍/👎 + optional reason — `POST /api/messages/{message_id}/feedback`.

This is the **capture** endpoint only — do NOT implement the LangMem learn step, the demotion of
memories on thumbs-down, or the frontend UI here; those are separate tasks (P9-03, P9-09). This task
must, however, produce a clean, reusable persistence layer (repository/model) that the later learn-step
task can read from (e.g. "give me recent thumbs-down feedback for user X").

## Acceptance criteria
- [ ] New table/model `message_feedback` (or equivalent) with: message id (FK to the existing messages
      table from P1/P2), user id (or guest session id) for ownership, rating (up/down enum or boolean),
      optional reason text, created_at.
- [ ] Alembic migration added following the existing migration conventions (see P2-02/P2-03..05).
- [ ] `POST /api/messages/{message_id}/feedback` — validates the message exists and belongs to the
      caller (session/user), upserts feedback for that message+user (idempotent — resubmitting changes
      the same row, does not duplicate), returns the stored feedback.
- [ ] Repository method(s) to fetch feedback by message id and to list a user's recent thumbs-down
      feedback (for later consumption by P9-03).
- [ ] AuthZ/rate-limit: reuses the existing per-session/per-user auth dependencies (P3-04) — guests can
      give feedback too (guest session ownership), no new unauthenticated surface.
- [ ] Unit/integration tests covering: happy path up/down, idempotent resubmission, feedback on a
      nonexistent message (404), feedback on a message the caller doesn't own (403/404).

## Design references
- dev-board/plan.md: P9 — Personalization (teachable memory) + response feedback
- dev-board/app-design-and-features.md: §7 (feedback / memory), §7.6 (PII/GDPR handling — do not put PII
  requirements in scope here, but keep the reason field a plain free-text column, no special handling
  needed yet at capture time)
- Existing conventions: `dev-board/code-review/P1-07-message-id/`, `dev-board/code-review/P2-*` for
  repository/migration patterns.

## Constraints / non-goals
- No LangMem wiring, no memory extraction, no demotion logic — capture only.
- No frontend changes.
- Do not rename or restructure the existing messages/conversations schema beyond what's needed to add
  this table.
