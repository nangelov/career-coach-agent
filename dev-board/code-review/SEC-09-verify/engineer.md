# Engineer report — SEC-09-verify · Revision 1

## Summary
Verification pass over the whole SEC block (SEC-01..SEC-08). Ran the full backend + frontend
suites together, and added/strengthened targeted regression coverage for the two cross-cutting
claims that no single prior task owned end to end. Found no security regressions; one genuine
**test-coverage gap** (SEC-05 cascade assertions covered only 5 of ~14 user-owned tables) and one
**missing end-to-end proof** (SSRF blocked through the real crawler entrypoint, not just the
guard's own units) — both fixed with narrowly-scoped test-only changes. No product code changed.

Live verification was possible: Docker was available (the stack was *not* pre-running), so I
brought up the compose Postgres via the `docker-compose.dev-ports.yml` override, migrated to head,
and ran the full suite against real Postgres — **548 passed, 1 skipped** (only a heavy-ML
importorskip remains). Container + volumes torn down afterward.

## Files changed
- `backend/tests/test_sec_exit_verification.py` (new) — SEC-block exit module. Drives SSRF probes
  (loopback `127.0.0.1`, link-local `169.254.169.254`, and a public→private 302 redirect chain)
  through the **real** crawler entrypoint `agents.web_searcher.search_and_crawl`, asserting the
  private target is never fetched (recorded fetch list) while the crawl fails soft (turn not
  crashed, result still cited). Plus a mixed case proving a blocked probe is a per-URL skip that
  doesn't abort a legitimate public crawl.
- `backend/tests/test_account_repository_postgres.py` (modified) — strengthened
  `test_delete_user_cascades_every_store` to assert **zero surviving rows in every** seeded
  user-owned table (Profile, Preference, Session, Conversation, MessageFeedback, UserMemory,
  KbDocument, Pdp, Goal, ProgressEntry) plus grandchildren reached via their parent FK (Message
  via Conversation, KbChunk via KbDocument, Milestone/DashboardTask via Goal) — previously only 5
  tables were checked, so the "no orphan rows" claim was under-proven. Added a small `_owned()`
  count helper (DRY).

## Key decisions
- **Gap fix, not re-implementation** (task constraint). The SSRF guard, injection fencing, redaction,
  consent gate, legal pages, token-free BFF, and cascade *behavior* are all already correct and
  covered; I only added the missing *cross-cutting* proofs. All content-bearing FKs verified
  `ON DELETE CASCADE` (identity/dashboard/knowledge models), so the strengthened count-based
  assertions are meaningful (the retained `feedback` row is SET NULL by design and stays covered
  by the separate contact-scrub test).
- **SSRF proven through the crawler seam** (design §7.2), reusing the approved test seam:
  `build_guarded_client(inner_transport=MockTransport, resolver=...)` with a scripted resolver
  mapping probe hosts to private IPs — no real network/DNS. This closes the task's stated concern
  that only the guard's own units, not the crawler path, exercised the block.
- Verified the other claims are already fully owned (no new tests needed) — see below.

## Verification of each cross-cutting claim
- **SSRF probes blocked through the real crawler** — NEW tests (4) in `test_sec_exit_verification.py`. Pass.
- **Injected instructions not followed** (CV + crawled page) — already owned end to end by
  `test_untrusted_content.py` (`test_cv_injection_is_fenced_and_ignored`,
  `test_crawled_page_injection_is_fenced_in_grounding_block`,
  `test_responder_prompt_fences_poisoned_worker_content`, output-net scrub) and
  `test_web_searcher.py::test_crawled_instructions_are_inert_text_only`. Confirmed, no gap.
- **Only the UI port is reachable** — `docker compose -f docker-compose.yml config` shows
  `frontend` publishes `3000:3000`; `db`/`redis`/`backend`/`worker` publish **none**. Confirmed.
- **No token in JS/localStorage/URL** — grep: no `localStorage`/`sessionStorage` writes; the token
  lives only in the httpOnly cookie, injected server-side in `lib/bffProxy.ts`. Frontend test
  `bffSession.test.ts` already asserts `clientSessionState(...)` is token-free
  (`JSON.stringify(state)).not.toContain(token)`). Confirmed, no gap.
- **Delete-account leaves no orphan rows** — STRENGTHENED test, run **live against real Postgres**:
  every user-owned + grandchild table is empty post-erasure while a second user and shared KB
  survive. Pass.
- **Consent gate + privacy/ToS** — `test_auth_service.py::test_create_guest_session_without_consent_is_rejected`,
  `test_auth_api.py::test_guest_endpoint_rejects_missing_consent`, and frontend
  `legalPages.test.tsx` (pages render with no session + required GDPR disclosures). Confirmed.
- **Contact-detail redaction through `LLMRouter`** — `test_llm_redaction.py::test_complete_redacts_before_client_call`
  / `test_stream_redacts_before_client_call` (email/phone stripped before the underlying client,
  substance preserved). Confirmed.

## How to verify
- New SSRF crawler tests: `cd backend && uv run --no-sync pytest tests/test_sec_exit_verification.py -v`
- Live cascade proof: bring up DB + migrate + run —
  `docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml up -d --wait db`,
  `cd backend && make migrate-integration && make test-integration`.
- Port lockdown: `docker compose -f docker-compose.yml config` (only `frontend` has `ports:`).

## Tests (final step — mandatory)
- Backend (no DB): `uv run --no-sync pytest` → **495 passed, 54 skipped** (491 baseline + 4 new
  SSRF tests; strengthened cascade test skips cleanly without a DB).
- Backend (live Postgres, dev-ports override + migrated): **548 passed, 1 skipped** — all
  previously-skipped live-Postgres tests ran, including the strengthened cascade/export tests.
- Frontend: `npx jest` → **135 passed, 14 suites**.
- Lint/format on changed files: `ruff check` + `ruff format --check` clean. (Tests are outside the
  mypy gate — `typecheck` targets `app/`+`migrations/` only — and the untyped test helpers match
  the existing `test_ssrf_guard.py` style.)
- No failures; nothing to root-cause. DB container + volumes torn down after the live run.

## Self-check
- [x] Meets acceptance criteria (all boxes: suites green; SSRF probes blocked through real crawler;
      injection inertness confirmed; only frontend port published; no token in JS/localStorage/URL;
      cascade completeness proven live; consent/legal spot-checked; redaction spot-checked; the one
      coverage gap found was fixed).
- [x] No secrets committed (`.env` is gitignored; only used transiently for the live-DB run).
      Verification-only — no product code touched, layering untouched.
- [x] Tests/lints pass (results above).
