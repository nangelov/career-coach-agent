# Code review — SEC-09-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/tests/test_account_repository_postgres.py (whole) · test_sec_exit_verification.py | Live-Postgres cascade completeness ("548 passed") and the frontend suite ("135 passed") could not be independently re-run in this review sandbox (no running DB / jest not executed); they rest on the engineer's reported live run. | None required — the SSRF crawler tests, backend no-DB suite, port config, and token grep were all re-run here and pass; note this residual reliance only. |

## Notes
Verification is genuine, not report-re-reading. I independently confirmed:

- **SSRF through the real crawler** — `test_sec_exit_verification.py` drives `agents.web_searcher.search_and_crawl` + `net.ssrf_guard.build_guarded_client` (real code, MockTransport + scripted resolver). Re-ran: **4 passed**. The loopback/link-local cases assert `served == []` (private host never reached the transport); the redirect case asserts `served == ["http://public-probe.test/start"]`, proving the guard blocks on the re-validated 2nd hop, not that nothing was fetched. Meaningful end-to-end proof.
- **Backend suite green** — re-ran `pytest -q`: **495 passed, 54 skipped** (matches the report; the strengthened live-DB cascade test skips cleanly without a DB and still imports/collects, so its model refs are valid).
- **Cascade test is well-formed** — `_owned()` references `user_id` on every listed model (Profile/Preference/Session/Conversation/MessageFeedback/UserMemory/KbDocument/Pdp/Goal/ProgressEntry all have it); grandchildren (Message/KbChunk/Milestone/DashboardTask) correctly counted via parent-FK joins since they carry no direct `user_id`. The strengthened assertions would fail loudly if any FK cascade were incomplete.
- **"Already owned" claims are real, not fabricated** — grep-confirmed every cited test exists: injection (`test_cv_injection_is_fenced_and_ignored`, `test_crawled_page_injection_is_fenced_in_grounding_block`, `test_responder_prompt_fences_poisoned_worker_content`, `test_crawled_instructions_are_inert_text_only`), redaction (`test_complete_redacts_before_client_call`/`test_stream_redacts_before_client_call`), consent (`test_create_guest_session_without_consent_is_rejected`, `test_guest_endpoint_rejects_missing_consent`), token-free BFF (`bffSession.test.ts` asserts state `.not.toContain(token)`), legal pages.
- **Port lockdown (SEC-03)** — `docker compose config` shows exactly one `ports:` block, `frontend` → 3000; db/redis/backend/worker publish none.
- **No token in JS/localStorage (SEC-04)** — grep of `frontend/lib|components|app` finds only comments documenting the httpOnly-cookie posture; no `localStorage`/`sessionStorage` token writes.

Scope discipline is correct: only **two test files** changed (new `test_sec_exit_verification.py`, strengthened cascade test), **no product code** — verification + narrowly-scoped gap-filling exactly as the task demanded. The two gaps found (SSRF-through-crawler proof, under-covered cascade assertions of 5/~14 tables) were real and appropriately closed with test-only changes. No blockers, no majors.
