# Engineer report — P8-04-pdp-seed-dashboard · Revision 1

## Summary
A successful `POST /api/pdp` generation now seeds the caller's living-PDP dashboard so the one-shot
PDF becomes the start of a trackable plan (§5.2). Seeding creates (or reuses) one `source="ai"`
goal for the career goal, plus milestones parsed from the plan's `learning_objectives` section and
tasks parsed from `timeline_action_steps` — all `source="ai"` → the P8-02 `DashboardService`
resolves them to `status="proposed"` (pending user approval, reused verbatim, no re-implementation).
Seeding runs after a successful `PdpGenerated` outcome and is **fail-soft**: any dashboard-write
error is logged and swallowed so the PDF is still returned.

## Files changed
- `app/services/pdp_seed.py` (new) — the PDP→dashboard translation: `parse_line_items` (deterministic
  bullet/numbered-list extractor with markdown stripping) + `seed_dashboard_from_pdp` (goal
  reuse/de-dup rule, milestone/task seeding). Keeps this logic out of `PdpService` (SoC).
- `app/services/pdp.py` — `PdpService.__init__` takes a `dashboard: DashboardService`; after a
  successful generation/persist, `_seed_dashboard(...)` runs the seeding wrapped in a fail-soft
  try/except (PDF never blocked).
- `app/bootstrap.py` — `build_pdp_service` injects `build_dashboard_service(app)` (reuses P8-02
  store wiring, no duplication — same pattern P8-03 used for `build_chat_service`).
- `tests/test_pdp_seed.py` (new) — unit tests for the line-item parser.
- `tests/test_pdp_service.py` — thread `dashboard` through the `_service` helper; add seeding-flow,
  regeneration-de-dup, and seeding-failure-fail-soft tests.
- `tests/test_p7_exit_verification.py` — pass a `DashboardService` to the real `PdpService`.

## Key decisions
- **Section→row mapping (task §"What to seed", §5.2):** `learning_objectives` → milestones,
  `timeline_action_steps` → tasks (the two action-item sections). Assessment/reference sections are
  never seeded. Nothing is invented: an unparseable section seeds no rows; the goal alone still
  lands.
- **Deterministic parser, not a second LLM pass (task constraint):** `parse_line_items` keeps only
  `-`/`*`/`•` bullets or `1.`/`1)` numbered lines, strips markdown emphasis/inline-code/checkboxes,
  de-dups case-insensitively within a section, truncates to the shared 512-char `title` cap, and
  caps at 25 items/section (defensive bound so a pathological plan can't flood the dashboard).
- **De-dup / reuse rule (task §"Regeneration must not spam duplicates"):** find the caller's first
  non-`abandoned` goal whose `title` **or** `target_role` equals the career goal case-insensitively;
  reuse it (refreshing `target_date` when a new one is given) and add only milestones/tasks whose
  title isn't already present — otherwise create a fresh `source="ai"` goal. Deliberately an exact
  case-insensitive match (simple, testable), not a fuzzy matcher. Rationale: `pdps` rows are
  append-only by design, but the dashboard is a living surface, so regenerating the same goal must
  not spawn a duplicate goal/rows.
- **Attribution reuses P8-02 verbatim (§5.2, task §"Attribution"):** every write passes
  `source="ai"`; `status` is never set here — the service resolves `ai` → `proposed`. Matches
  P8-03's tool-write posture (a generated plan means the AI authored the specific items → review on
  dashboard, never silently active).
- **Fail-soft (task §"Fail-soft"):** `_seed_dashboard` swallows and logs any exception so a dashboard
  hiccup never fails the PDF response.
- **`dashboard` is a required (non-optional) ctor arg:** PDP already requires Postgres
  (`_require_pg_provider` fails loudly), so the dashboard service is always available — no optional
  degrade path needed (unlike `build_chat_service`, whose Postgres is optional).

## How to verify
- `make test` (or `uv run --no-sync pytest`) — full suite.
- Targeted: `uv run --no-sync pytest tests/test_pdp_seed.py tests/test_pdp_service.py -q`.
- `uv run --no-sync ruff check . && ruff format --check . && mypy app/`.

## Tests (final step — mandatory)
- `uv run --no-sync pytest` → **719 passed, 62 skipped**.
- `uv run --no-sync ruff check` (changed files) → All checks passed. `ruff format --check` → clean.
- `uv run --no-sync mypy app/` → Success: no issues found in 130 source files.
- Fixes made while getting green (all test-side, no behavior weakened): imported `date` in
  `test_pdp_service.py`; gave the regeneration test a 2-read role session (two `generate()` calls →
  two skills-gap reads — mirrors the FreshSession lesson for sequential DB reads); refined
  `_clean_item` so single-`*` emphasis is stripped anywhere in a line (not just at the ends);
  threaded `dashboard` into `test_p7_exit_verification.py`'s real-`PdpService` builder.

## Self-check
- [x] Meets acceptance criteria (seed one proposed goal+rows; regeneration doesn't duplicate;
      seeding failure doesn't fail the PDF; parser + service-flow unit tests — all covered/tested).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (seeding lives in the
      service layer; store wiring reused via the composition root; no DB drivers in services).
- [x] Tests/lints/typecheck pass (pasted above).
