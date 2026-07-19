# Task P9-05-memory-crud-api — memory panel API (silent-but-viewable/deletable)
- **Phase:** P9   **Status:** ENG   **Tags:** (B)

## Scope
Implement the API backing the "What the coach knows about you" panel: viewing and editing
explicit `preferences`, and viewing/deleting learned `user_memories` — no per-fact confirmation
prompts, since application is already silent (P9-02/P9-03 apply learned context automatically).
This task is the **transparency & control** surface [DECIDED §6.7/§6.10]: opt-out, not opt-in.

From `dev-board/tasks.md` (P9), two bullets covered together (same surface):
> Learned-memory application = **silent-but-viewable/deletable (opt-out)** [DECIDED §6.10] —
> memory panel, no per-fact confirmation prompts.
> `GET/PUT/DELETE /api/memory` (view/edit/delete learned memories + preferences).

### What already exists (read before building)
- `backend/app/memory/store.py::UserMemoryStore` — already has `add_memory` / `update_memory` /
  `delete_memory` / `list_memories_for_message` (P9-03). **No "list all memories for a user"
  method yet** — add one (e.g. `list_memories(user_id)`), backed by a new
  `vector_search.py` primitive (or an existing one you can extend) that does a plain (non-vector)
  `SELECT ... WHERE user_id = :uid ORDER BY created_at DESC` — no query embedding needed for a
  full listing.
- `backend/app/repositories/models/identity.py::Preference` — `preferences` table, one JSONB
  `data` row per user. Find the existing repository/service reading/writing it (grep for
  `Preference` usage — it may already have a read path from account export (SEC-05) but check
  whether a **write** path exists; if not, add one following the same
  "open session, caller commits" convention as `vector_search.py`).
- `backend/app/api/dashboard.py` / `backend/app/api/message_feedback.py` — the router pattern to
  mirror exactly: thin `APIRouter`, `require_auth`, ownership always taken from the verified
  token subject (never a path/body user id), guests rejected (memory is durable-only, §5.4 —
  guests have no `user_memories`/`preferences` row to view), lazy service via
  `app.bootstrap`/`app.app_state`.
- `backend/app/schemas/dashboard.py` — the Pydantic request/response shape convention to mirror
  for new `app/schemas/memory.py` models.

## Acceptance criteria
- [ ] `GET /api/memory` — returns the caller's explicit `preferences` (structured settings) and
      the list of their durable `user_memories` (id, text, memory_type, confidence, created_at
      — no embeddings in the response). Guests → `403` (mirrors dashboard's `_require_user`).
- [ ] `PUT /api/memory/preferences` (or `PUT /api/memory` scoped to preferences — your call,
      document it) — updates the caller's explicit `preferences.data` JSONB (tone, formality,
      language, focus areas, do/don't list per §5.4). Upserts if no row exists yet.
- [ ] `DELETE /api/memory/{memory_id}` — deletes one learned memory, **scoped to the caller**
      (a memory id that exists but belongs to another user → `404`, not `403`, mirroring the
      no-ownership-leak convention already used in `message_feedback`/`dashboard`).
- [ ] (Optional but encouraged if cheap) `DELETE /api/memory` — bulk-clear all of the caller's
      learned memories (a natural "forget everything you've learned about me" action for the
      panel) — if you add it, keep `preferences` untouched (explicit settings are a separate,
      user-authored thing, not "learned").
- [ ] **Explicit edits override inferred memories** (§5.4 point 4) — this is satisfied simply by
      `preferences` being authoritative and always injected ahead of/alongside `memories` in
      recall (P9-02 already does this — confirm by reading `app/agents/memory_agent.py`, do not
      re-implement recall here); note the confirmation in `engineer.md`.
- [ ] No per-fact confirmation prompt/workflow of any kind — deletion and preference edits are
      immediate, not queued for approval (contrast with the P8-03 dashboard's `source="ai"`
      propose/approve flow — memory is explicitly **not** that model, §6.10).
- [ ] Unit + integration tests: view with data / view empty (new user) / guest 403 / update
      preferences / delete own memory / delete someone else's memory → 404 / delete unknown id →
      404.

## Design references
- dev-board/app-design-and-features.md: §5.4 point 4 ("Transparency & control... 'What the coach
  knows about you' panel... Explicit edits override inferred memories"); §6.7 point 10
  ("Learned-memory application → silent-but-viewable/deletable (opt-out). [DECIDED]").
- dev-board/plan.md: P9.
- `backend/app/api/dashboard.py`, `backend/app/api/message_feedback.py` (router/auth precedent).

## Constraints / non-goals
- No frontend UI — that is P9-09 (this task is the API only).
- No confirmation-prompt workflow — explicitly rejected by §6.10 for this feature.
- Do not touch the recall (P9-02) or learn (P9-03/04) pipelines beyond what's needed to add the
  "list all" read primitive; this task is CRUD surface only.
- No guest personalization (Redis) work — that is P9-07.
