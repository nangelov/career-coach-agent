# Engineer report — P7-03-pdp-endpoint · Revision 2

## Summary
Wired the P7-01 PDP agent + P7-02 PDF builder into a new `POST /api/pdp` endpoint that generates
a styled PDF from the caller's **stored** structured profile (no re-upload). Follows the house
Router → Service → Agent/Repository pattern (mirrors `roles.py` / `profile.py`): a thin router, a
new `PdpService` policy layer, a new `PdpStore` port + Postgres adapter for persistence, and a
lazy `build_pdp_service` composition-root builder cached on `app.state`.

Flow: load stored profile → (missing → 422) → compute skills gap via the reused P6-05
`SkillsGapService` → generate the six-section plan (`generate_pdp`) → gate with
`validate_pdp_content`, **one bounded retry** → render `build_pdp_pdf` → persist a `pdps` row →
return the PDF (`application/pdf`, `PDP_<goal>.pdf`, `X-PDP-Status` header).

## Files changed
- `backend/app/schemas/pdp.py` — added `PdpRequest` (career_goal / target_date / additional_context; no file). Reuses existing `PdpContent`.
- `backend/app/services/pdp_store.py` (new) — `PdpStore` ABC port + `InMemoryPdpStore` test double (interface-before-implementation, like `ProfileStore`).
- `backend/app/repositories/pdp_store.py` (new) — `PostgresPdpStore` adapter: inserts a `Pdp` row (`content` = `PdpContent.model_dump(mode="json")`) over the shared PG provider.
- `backend/app/services/pdp.py` (new) — `PdpService` policy layer + discriminated outcomes (`PdpGenerated` / `PdpProfileMissing` / `PdpGenerationFailed`).
- `backend/app/api/pdp.py` (new) — thin router; auth-gated, guests 403, rate-limit reuse, outcome→status mapping, PDF response.
- `backend/app/bootstrap.py` — `build_pdp_service` (deferred heavy imports; `_require_pg_provider`; redis-wired `LLMRouter`).
- `backend/app/app_state.py` — `PDP_SERVICE` key.
- `backend/app/main.py` — register `pdp_router`.
- `backend/tests/test_pdp_service.py` (new), `backend/tests/test_pdp_api.py` (new).

## Key decisions
- **Unmined role → degrade to a profile-only best-effort PDP (not a 202 mine-and-poll).** The task
  allowed either; a PDP is a one-shot download the user asked for *now*, and `generate_pdp` already
  handles `role_profile_missing`, so returning a usable plan beats a poll round-trip. The unmined
  state is still signalled: the plan's Skills Gap section says so, and the endpoint stamps
  `X-PDP-Status: role_profile_missing` (machine-readable, without breaking the PDF stream). Missing
  *profile* stays a hard 422 (no plan is meaningful without a profile). (§5.6 / task.)
- **Synchronous, not Celery** — single bounded-token LLM call over already-parsed data; `plan.md`/
  `tasks.md` don't call out Celery here, so it runs in-request (v1 posture). Documented seam to move
  behind a task if it ever exceeds a request timeout.
- **No role canonicalization in this endpoint** — keeps `PdpService` free of the embedder/ML stack;
  an unmined spelling simply degrades to best-effort (the same graceful path). Noted as a documented
  simplification (a canonical resolver can slot in behind the same call later).
- **Regenerate = append a new `pdps` row** per generation (a PDP is a point-in-time record; matches
  "a `Pdp` row is persisted per generation" and P8 dashboard-seeding reads).
- **Bounded retry** = 2 attempts total (`_MAX_VALIDATION_ATTEMPTS`), mirroring v1's `max_retries`;
  a persistent validation failure → `PdpGenerationFailed` → 502, never a broken/persisted PDF.
- **`additional_context`** folded into the agent's *trusted* turn text (`_effective_goal`); the raw
  `career_goal` is what's persisted, keeping the stored record clean.
- **422 literal** (not `status.HTTP_422_...`) to dodge Starlette's constant-rename deprecation,
  matching `profile.py`'s literal-413 convention.
- Did **not** touch the `pdps` migration/schema (no gap found) or extend `generate_pdp`'s signature.

## How to verify
```
cd backend
.venv/bin/python -m pytest tests/test_pdp_api.py tests/test_pdp_service.py -q
.venv/bin/ruff check app/api/pdp.py app/services/pdp.py app/services/pdp_store.py \
    app/repositories/pdp_store.py app/schemas/pdp.py app/bootstrap.py
.venv/bin/mypy app/api/pdp.py app/services/pdp.py app/services/pdp_store.py \
    app/repositories/pdp_store.py app/schemas/pdp.py app/bootstrap.py
```

## Tests (final step — mandatory)
- `pytest tests/test_pdp_api.py tests/test_pdp_service.py -q` → **13 passed**.
- Full suite `pytest -q` → **642 passed, 59 skipped** (skips are pre-existing live-DB/integration
  tests, unrelated to this task).
- `ruff check` (all changed files incl. tests) → **All checks passed**.
- `mypy` (6 new/changed source files) → **Success: no issues found**.
- No failures to root-cause.

Coverage: service — happy path (PDF + one persisted row), missing profile (short-circuits, no LLM
call, no row), unmined role (best-effort plan, `role_profile_missing`), validation retry (thin→full
succeeds on 2nd attempt), retry exhausted (502-equivalent, no row). API — 401 (no token), 403
(guest, service not called), 200 PDF (content-type/filename/`X-PDP-Status`, token subject used),
unmined 200 + header, 422 (missing profile), 502 (failed), 429 (over budget, service not called),
422 (blank goal body validation).

## Self-check
- [x] Meets acceptance criteria: auth-gated `POST /api/pdp`, stored-profile only (no multipart),
  styled PDF; missing profile/unmined role degrade non-5xx; `validate_pdp_content` gates every PDF
  with one retry; a `Pdp` row persisted per generation; unit tests for all four required paths.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (router HTTP-only, service
  depends on ports, no SQLAlchemy in service/router).
- [x] Tests/lints/types pass (pasted above).

---

# Revision 2 — Response to review

Code-review verdict was `CHANGES_REQUESTED` (C1 blocker + C2/C3 minors); architecture-review was
already `APPROVED` (no changes requested there). All findings addressed below.

## Tests (revision 2 — final step, mandatory)
- `pytest tests/test_pdp_api.py tests/test_pdp_service.py tests/test_pdp_agent.py -q` → **23 passed**.
- Full suite `pytest -q` → **643 passed, 59 skipped** (up one net test from r1's 642; skips are the
  same pre-existing live-DB/integration tests, untouched by this task). No failures to root-cause.
- `ruff check` (changed source + tests) → **All checks passed**.
- `mypy app/agents/pdp_agent.py app/services/pdp.py app/schemas/pdp.py` → **Success: no issues found**.

## Response to review

### C1 (major, blocker) — LLM-outage fallback text passed validation and was silently persisted/returned — FIXED
Root cause: `generate_pdp` returned `_fallback_sections()` (six placeholder sentences = 534 chars,
6 sections) with `status` left at `ok`/`role_profile_missing` on any `LLMError`/unusable tool call.
That passed `validate_pdp_content`, so the service treated it as success — persisting a placeholder
`pdps` row and returning a 200 PDF; `PdpGenerationFailed` was only reachable on a "thin but
successful" tool call.

Fix (the reviewer's *preferred* option — surface the failure explicitly at the P7-01 seam):
- **`app/schemas/pdp.py`** — added a fourth `PdpStatus` literal `"generation_failed"` (documented:
  a profile existed but synthesis failed; the bodies are honest placeholders, *not* a real plan).
- **`app/agents/pdp_agent.py`** — `_synthesize_sections` now returns `dict | None` (`None` = a real
  synthesis failure: `LLMError` **or** unusable/absent tool call). `generate_pdp` maps `None` to a
  new `_degraded_generation_failed(resources)` → a `PdpContent(status="generation_failed", …)`
  (still renderable, but explicitly flagged). `_fallback_sections` is reused for the placeholder
  bodies; no other status path changed.
- **`app/services/pdp.py`** — the bounded-retry loop now rejects any attempt whose
  `content.status == "generation_failed"` (retries within the same 2-attempt budget, then the
  `for…else` returns `PdpGenerationFailed`). So a real LLM outage now maps to **502, no `pdps` row**
  — the `PdpGenerationFailed` path is reachable for the *most likely* failure mode, restoring v1's
  "clear error, never a broken PDF" semantics and keeping P8's dashboard from being seeded with
  placeholder content.
- **Tests** — added `test_pdp_service.py::test_llm_outage_fails_without_persisting_placeholder_plan`
  (drives a `RaisingCompleter` that raises `LLMAllModelsFailedError` on every call; asserts
  `PdpGenerationFailed`, `store.saved == []`, and 2 attempts). Updated the now-stale agent test
  `test_llm_failure_falls_back_to_honest_sections` → `test_llm_failure_reports_generation_failed_status`
  (it asserted the exact masked-failure behavior the reviewer flagged: `status == "ok"` on an LLM
  outage; it now asserts `status == "generation_failed"`, still fully renderable). This was a test
  encoding stale/incorrect behavior, fixed at the root, not weakened to pass.

Budget note (the "ideally no budget charge" in C1): kept the `MESSAGE` charge on a synthesis
failure — the LLM work *was* attempted (up to two real calls), so the charge reflects consumed
effort, and there is no refund primitive in `RateLimitService`. This is deliberate and mirrors
`chat.py` (charged before the model decides). The no-work case (missing profile) is C3 below.

### C2 (minor) — redundant profile fetch (`generate` + `SkillsGapService.compute` each read the profile) — DOCUMENTED (deliberate double-read)
Kept the two reads and documented the rationale inline in `app/services/pdp.py`: threading the
already-loaded profile through `SkillsGapService.compute(user_id, role)` would change the shared
P6-05 service contract (also consumed by `roles.py`) for one caller's micro-optimization. The
second read is a cheap PK-indexed lookup; the coupling isn't worth it (KISS/YAGNI). Chose the
reviewer's explicit "document the deliberate double-read" alternative over the refactor.

### C3 (minor) — a profile-less user is charged a MESSAGE budget unit before the 422 — ACCEPTED & NOTED
Not changed. Moving the profile-existence short-circuit ahead of the budget charge would require
either leaking profile-existence into the router (breaking Router→Service, since profile resolution
is the service's job) or a second service round-trip / a bespoke "peek" method — added complexity
for a benign edge. The charge is a single message unit; the caller gets an immediate, clear 422
("upload a CV first") and nothing legitimate is deterred. This matches `chat.py`'s posture (charge
before the model may decline). `roles.py::get_role_gap` not charging is consistent with it being a
cheap read; a PDP is a heavy LLM generation, so charging up-front for abuse-prevention is the right
default. Flagged as accepted per the reviewer's "accept and note it" option.

## Files changed (revision 2)
- `backend/app/schemas/pdp.py` — added `"generation_failed"` to `PdpStatus` (+ doc).
- `backend/app/agents/pdp_agent.py` — `_synthesize_sections` → `dict | None`; new
  `_degraded_generation_failed`; `generate_pdp` surfaces synthesis failure as `generation_failed`;
  docstrings updated.
- `backend/app/services/pdp.py` — retry loop rejects `generation_failed` attempts → 502/no row;
  C2 double-read documented; docstrings updated.
- `backend/tests/test_pdp_service.py` — new `RaisingCompleter` + LLM-outage test.
- `backend/tests/test_pdp_agent.py` — renamed/updated the LLM-failure test to assert
  `generation_failed`.
