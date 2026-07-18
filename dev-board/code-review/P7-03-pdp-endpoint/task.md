# Task P7-03-pdp-endpoint — `POST /api/pdp` using the stored profile (no re-upload)

- **Phase:** P7   **Status:** ENG   **Tags:** (B)

## Scope
Wire the P7-01 agent (`app.agents.pdp_agent.generate_pdp`) and P7-02 PDF builder
(`app.pdf.validate_pdp_content` / `app.pdf.build_pdp_pdf`) into a new `POST /api/pdp`
endpoint (new `backend/app/api/pdp.py` router), following the exact house pattern already
used by `app/api/roles.py` / `app/api/profile.py` (Router → Service → Agent/Repository, §8;
lazy service built by `app.bootstrap` and cached on `app.state` via `AppStateKeys`; auth via
`app.security.dependencies`).

Request/response contract (new `backend/app/schemas/pdp.py` additions or a sibling module —
check for naming collisions with P7-01's existing `app/schemas/pdp.py::PdpContent`, reuse it):
- **Input:** `career_goal: str`, `target_date: date | None`, `additional_context: str | None`
  — **no file upload**. Auth required (mirrors `GET /api/roles/{role}/gap` — guests are
  rejected with 403, since PDP generation needs a persisted profile, which only logged-in
  users have per P5).
- **Flow:** load the caller's stored structured profile (`ProfileStore.get`, P5) → if missing,
  403/422 with a clear "upload a CV first" message (no crash) → compute the skills gap for
  `career_goal` via the existing `SkillsGapService` (P6-05) — if the role has never been
  mined, decide (and document) whether to trigger mining (returns a 202 + task_id, same
  cold-start pattern as `roles.py`) or degrade gracefully to a profile-only PDP; either is
  acceptable, pick one and justify it in the report → call `generate_pdp(...)` (P7-01) →
  `validate_pdp_content(...)` (P7-02) — on failure, one bounded retry (mirrors v1's
  `max_retries` behavior) then a clear error, never a broken PDF → `build_pdp_pdf(...)` →
  persist a `Pdp` row (`app.repositories.models.dashboard.Pdp` — already migrated, P2-05:
  `user_id`, `career_goal`, `target_date`, `content` JSONB = `PdpContent.model_dump()`) →
  return the PDF (`StreamingResponse`/`Response` with `application/pdf` + a sensible
  filename, matching v1's naming convention).
- **Regenerate on demand:** calling the endpoint again for the same user/goal creates a new
  `pdps` row (or updates the latest — your call, document it) and returns a fresh PDF; no
  re-upload is ever required (the profile is already stored).

Also decide and implement whether this runs synchronously in the request (v1's approach —
the LLM call is one-shot with a bounded token budget, not a stream) or as a Celery task like
P5's CV parsing; `dev-board/plan.md`/`tasks.md` do **not** call out Celery for this endpoint
(unlike P5's explicit callout), so a synchronous implementation returning the PDF directly is
the expected default — only reach for Celery if you hit a concrete reason (e.g. the LLM call
routinely exceeds a reasonable request timeout). Document your choice either way.

## Acceptance criteria
- [ ] `POST /api/pdp` exists, auth-gated, uses only the stored profile (no `file`/multipart
      param), and returns a styled PDF.
- [ ] Missing profile / unmined role degrade with clear, non-5xx signals (mirrors
      `roles.py`'s `status`/202 patterns) — never a raw 500 or a broken PDF.
- [ ] `validate_pdp_content` gates every PDF returned; a validation failure is retried once
      then surfaced as a clear error (mirrors v1 semantics).
- [ ] A `Pdp` row is persisted per generation (`pdps` table, P2-05 schema) so a PDP is a
      first-class stored record, ready for P8's dashboard-seeding to read.
- [ ] Unit tests: happy path, missing-profile path, unmined-role path, validation-retry path
      (mock the agent/PDF builder — no real LLM/Postgres in unit tests, matches existing
      `roles`/`profile` test style with dependency overrides).

## Design references
- `dev-board/plan.md` — Phase 7 (`POST /api/pdp` uses the stored profile; regenerate on
  demand).
- `dev-board/app-design-and-features.md` — §5.2 (PDP → dashboard seed, forward reference for
  P8, not implemented here), §5.6 (skills gap → PDP), §9 (API surface).
- `backend/app/api/roles.py` — the router/service/auth/rate-limit pattern to mirror.
- `backend/app/bootstrap.py` — where to add `build_pdp_service` (or similar) following the
  existing `build_*_service` conventions.

## Constraints / non-goals
- Do not implement the frontend (P7-04) or dashboard seeding (P8) — persisting the `Pdp` row
  is in scope, wiring it into goals/tasks is not.
- Do not touch the `pdps` migration/schema unless you find a genuine gap — flag it instead.
- Reuse the existing rate-limit service (`RateLimitService`) the way `roles.py`/`chat.py` do;
  don't invent a second rate-limiting mechanism.
