# Task P8-04-pdp-seed-dashboard — PDP generation seeds goals/tasks into the dashboard
- **Phase:** P8   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P8 item: "PDP generation **seeds** goals/tasks into the dashboard."

`POST /api/pdp` (`app/services/pdp.py::PdpService.generate`) already produces a structured
`PdpContent` (`app/schemas/pdp.py`, six sections) and persists a `pdps` row. This task makes a
successful generation also seed the caller's living-PDP dashboard (`goals`/`milestones`/`tasks`,
P8-02's `DashboardService`) from that content, so the one-shot PDF becomes the start of a
trackable plan — without duplicating P8-02/P8-03's attribution logic.

**What to seed (design §5.2, §4 "Dashboard (living PDP)"):**
- One **goal**: `title`/`target_role` = the career goal, `target_date` = the request's
  `target_date` (nullable).
- **Milestones and/or tasks** derived from the plan's `learning_objectives` and
  `timeline_action_steps` sections (`PdpContent`, `app/schemas/pdp.py`) — these are the two
  sections that name concrete, actionable items. They are prose bodies (markdown-ish bullet
  lists), not already-structured lists, so extract line items deterministically (e.g. lines
  starting with `-`, `*`, a numeral + `.`/`)`, stripped of markdown) into individual
  milestone/task rows. If a section yields nothing parseable, degrade gracefully — seed the
  goal alone rather than fabricating tasks (never invent content not in the plan).
- Do **not** seed from `current_skills_assessment` / `skills_gap_analysis` /
  `recommended_training` / `progress_tracking_kpis` — those are assessment/reference sections,
  not action items.

**Attribution (must reuse P8-02's existing resolution, do not re-implement):** every seeded row
is an AI-authored proposal, so call `DashboardService` with `source="ai"` for the goal,
milestones, and tasks — the service already resolves that to `status="proposed"` (P8-02). This
is consistent with P8-03's tool-write posture: a PDP the user asked to *generate* still means
the AI *authored the specific plan items*, so they land as pending-approval, review-on-dashboard
proposals (never silently active) — same as everywhere else the AI writes.

**Regeneration must not spam duplicates.** `pdps` rows are append-only (a fresh row per
generation, by design) — but dashboard seeding is not: decide and implement a **sane
de-duplication/reuse rule** for "regenerate on demand" against the *same* career goal (e.g. find
an existing goal for this user whose `title`/`target_role` matches the career goal
case-insensitively and is not `abandoned`; reuse it — update its `target_date` and only add
*new* milestones/tasks not already present by title — rather than creating a second goal every
regeneration). Document the rule and its rationale in `engineer.md`; keep it simple and
testable, not a fuzzy-matching system.

**Fail-soft, never blocks the PDF.** Seeding runs **after** a successful `PdpGenerated` outcome
and must never fail the PDP response: if the dashboard write raises (DB hiccup, etc.), log and
still return the PDF — the user's download must not depend on dashboard availability. (Mirrors
the fail-soft posture used throughout the agents/tools.)

**Wiring:** inject `DashboardService` into `PdpService` (constructor) and thread it through
`app/bootstrap.py::build_pdp_service` (reuse `build_dashboard_service`, do not duplicate store
wiring — same pattern P8-03 used for `build_chat_service`). Guests are already rejected before
`PdpService.generate` runs (router-level `403`), so `user_id` is always a real account here.

## Acceptance criteria
- [ ] A successful `POST /api/pdp` call creates (or reuses, per the de-dup rule) exactly one
      `source="ai"`/`proposed` goal plus its parsed milestones/tasks, visible via
      `GET /api/dashboard`.
- [ ] Regenerating a PDP for the same career goal does not create a second duplicate goal (test
      it explicitly).
- [ ] A dashboard-write failure during seeding does not fail the `POST /api/pdp` response (PDF
      still returned) — test it explicitly (fake a raising `DashboardService`/store).
- [ ] Unit tests for the line-item parser (bullets, numbered lists, empty/unparseable sections)
      and for the service-level seeding flow (against the in-memory `DashboardStore`).

## Design references
- dev-board/app-design-and-features.md §5.2 (dashboard seeding, attribution, propose→approve),
  §4 "Dashboard (living PDP)".
- dev-board/plan.md Phase 7 ("Seeds the dashboard's goals/tasks") and Phase 8.
- `backend/app/services/pdp.py` (`PdpService.generate`), `backend/app/schemas/pdp.py`
  (`PdpContent`), `backend/app/services/dashboard.py` (`DashboardService`, already resolves
  `source="ai"` → `proposed` — reuse verbatim), `backend/app/bootstrap.py`
  (`build_pdp_service`, `build_dashboard_service`).

## Constraints / non-goals
- No new HTTP endpoints, no frontend UI (P8-05).
- No changes to the P7-01 agent's `PdpContent` schema/prompt — parse the existing prose
  sections; do not ask the LLM for a second structured pass.
