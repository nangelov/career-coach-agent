# Task FIX-07-market-role-canonicalization-kind-filter — filter taxonomy match by kind, not just source_type
- **Phase:** cross-cutting (P6 follow-up)   **Status:** ENG   **Tags:** (B)

## Scope
Follow-up flagged by `dev-board/code-review/P6-09-manual-verify/engineer.md` ("Flagged observation") and
confirmed as a real (non-blocking-for-P6-09, but real) conformance gap by both P6-09 reviews
(`code-review.md`, `architecture-review.md`).

**The bug:** `app/agents/market_agent.py::_resolve_baseline` (and its public wrapper
`resolve_canonical_role`, used by both the mining pipeline and the request-path
`GET /api/roles/{role}/requirements` / `/gap` to normalize a user-stated role) hybrid-searches the shared KB
via `shared_kb_document_ids(session, source_types=["curated"])`. **All three** shared-corpus producers now use
`source_type="curated"`: P6-01's taxonomy occupations, P6-04's role-profile summaries
(`meta={"canonical_role":..., "kind": ROLE_PROFILE_KIND}`), and P6-06's learning resources
(`meta={"kind": LEARNING_RESOURCE_KIND, ...}`). `_resolve_baseline` filters only on `source_type`, not on
`meta["kind"]`, and takes the single top hybrid-search hit (`k=1`). Under the normal/production condition
(taxonomy seeded, P6-01) the occupation document reliably outranks a role-profile summary titled *"Market
requirements: <role>"*, so today's tests pass — but nothing **structurally** stops `_resolve_baseline` from
matching a role-profile-summary or learning-resource document instead of a true taxonomy occupation when
ranking is close or the taxonomy has no good match for a role. When that happens, read-time canonicalization
can diverge from the `canonical_role` the mining pipeline actually persisted, causing
`GET /api/roles/{role}/requirements` to permanently miss the cached `role_profiles` row (perpetual `202` /
re-enqueue loop for that role).

**The fix:**
1. Add taxonomy documents' own explicit `kind` marker in `meta` (P6-01's `app/ingestion/taxonomy_seed.py`
   currently sets no `"kind"` key at all — see its `meta={"taxonomy":..., "taxonomy_id":..., "skills":...}`
   block). Introduce a shared, single-source-of-truth module for these string constants (e.g.
   `app/repositories/kb_kinds.py` or similar — pick a location with no import-cycle risk between `ingestion/`
   and `agents/`) so `TAXONOMY_KIND`, `ROLE_PROFILE_KIND` (currently defined in `market_agent.py`), and
   `LEARNING_RESOURCE_KIND` (currently defined in `learning_resources.py`) all live in one place and every
   producer/consumer imports from it — do not leave three independently-defined string literals that can drift.
2. Stamp `meta["kind"] = TAXONOMY_KIND` on taxonomy `KbDocument` rows (and their chunks, for consistency with
   how the other two producers stamp both).
3. `_resolve_baseline` must restrict its taxonomy match to `meta.get("kind") == TAXONOMY_KIND` — not rely on
   ranking alone. Since hybrid search doesn't filter on JSONB `meta` at the SQL level today, the pragmatic fix
   is: request a small top-k (e.g. `k=5`) instead of `k=1`, then pick the **first** hit whose parent
   `KbDocument.meta.get("kind") == TAXONOMY_KIND`; fall back to the no-match `_Baseline` (as today) if none of
   the top-k qualify. Keep the change minimal and localized — do not introduce a new SQL-level JSONB filter
   parameter to `hybrid_search`/`hybrid_search_chunks` unless it's clearly the cheaper path (your call, but
   justify it in the report if you go that route).

## Acceptance criteria
- [ ] A regression test proves the bug **would have failed before the fix**: seed the shared KB with a
      role-profile-summary document (`kind=ROLE_PROFILE_KIND`) that out-ranks (or ties) a true taxonomy
      occupation document for a query, and assert `_resolve_baseline`/`resolve_canonical_role` still returns
      the taxonomy occupation's canonical title, not the summary's.
- [ ] `TAXONOMY_KIND`/`ROLE_PROFILE_KIND`/`LEARNING_RESOURCE_KIND` are defined once and imported everywhere
      they're used (grep to confirm no duplicate string-literal definitions remain).
- [ ] Existing P6-01/P6-04/P6-06/P6-07/P6-09 test suites still pass unmodified in behavior (only the new
      `meta["kind"]` field and the `_resolve_baseline` top-k+filter logic change) — no regression.
- [ ] Full backend test suite green (`ruff check`, `ruff format --check`, `mypy` on `app/`+`migrations/`,
      `pytest`, including the live-DB-gated `test_p6_exit_verification.py` if a live Postgres is available in
      this environment — otherwise document that it was not re-run live and why).

## Design references
- dev-board/app-design-and-features.md §5.6 (role_profiles is keyed once per canonical role, reused by all
  users — this bug threatens that invariant when it misfires)
- Prior art: `dev-board/code-review/P6-04-market-agent-and-guardrail/engineer.md`,
  `dev-board/code-review/P6-09-manual-verify/engineer.md` ("Flagged observation" section)

## Constraints / non-goals
- Do not change the `role_profiles`/`job_postings` schema (P6-02) or the `RolesService` cache contract
  (P6-07) — this is purely a canonicalization-matching fix inside `market_agent.py` (+ the shared `kind`
  constant refactor it requires).
