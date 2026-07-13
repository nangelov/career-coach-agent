# Architecture review — SEC-09-verify · engineer revision 1

## Verdict: APPROVED

Verification-only `(T)` task. No product code touched (`git status`: only `tests/test_sec_exit_verification.py`
new + `tests/test_account_repository_postgres.py` strengthened within the uncommitted SEC block). Layering,
seams, and locked decisions untouched. The pass genuinely closes the SEC block against the cited design
sections — the two cross-cutting proofs no prior SEC-0X task owned end-to-end are real, not superficial, and
every "already-owned" claim was spot-verified to exist in code.

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | S1 SSRF (§7.2) | Probes blocked through the **real crawler**, not just guard units | `test_sec_exit_verification.py` drives `search_and_crawl` over real `build_guarded_client`: loopback, link-local `169.254.169.254`, and **redirect-into-private 2nd-hop revalidation** all blocked (recorded fetch list proves private target never reached); per-URL fail-soft skip proven (safe page still crawls) | none |
| A2 | S2 untrusted content (§7.3/§6.14) | CV + crawled-page injections inert, both directions | Owned e2e by `test_untrusted_content.py` (`test_cv_injection_is_fenced_and_ignored`, `test_crawled_page_injection_is_fenced_in_grounding_block`, `test_responder_prompt_fences_poisoned_worker_content`) + `test_web_searcher.py::test_crawled_instructions_are_inert_text_only` — all confirmed present | none |
| A3 | S5 GDPR erasure (§7.6, Art.17) | `DELETE /api/me` cascades **every** store, no orphans, scoped | Strengthened `test_delete_user_cascades_every_store`: seed populates all 10 owned tables + 4 grandchildren (Message/KbChunk/Milestone/DashboardTask), asserts zero survivors + second user + shared `user_id IS NULL` KB survive; run **live vs Postgres** (548 passed) | none |
| A4 | S4 BFF transport (§6.13) | Token never in JS/localStorage/URL | `bffSession.test.ts` asserts `clientSessionState` token-free; token only in httpOnly `cc_session` cookie (server-injected in `lib/bffProxy.ts`); grep clean | none |
| A5 | S3 port lockdown (§6.12/§7.2) | Only UI port published | `docker-compose.yml`: only `frontend` has `ports: 3000:3000`; db/redis/backend/worker publish none; 5432/6379/8000 are internal-network only | none |
| A6 | S6 consent gate (§6.22) | No session without consent | `test_auth_service.py::test_create_guest_session_without_consent_is_rejected` + `test_auth_api.py::test_guest_endpoint_rejects_missing_consent` present | none |
| A7 | S7 privacy/ToS (§6.17/§6.22) | Pages reachable pre-login w/ GDPR disclosures | `legalPages.test.tsx` renders Privacy + Terms from bare `render()` (no auth wiring = the reachability proof), pins required disclosures | none |
| A8 | S8 contact redaction (§6.16) | Contact-only strip at LLM egress, substance kept | `test_llm_redaction.py::test_complete_redacts_before_client_call` / `test_stream_redacts_before_client_call` — email/phone stripped before client, substance intact; matches contact-only locked ruling | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — verification-only, no product/layer changes; SSRF proof reuses the blessed `app/net/` guarded-client seam, cascade proof exercises the `repositories/account.py` port
- [x] Honors locked decisions — no new failover/redaction mechanism, Postgres+Redis only, contact-only redaction respected
- [x] Interfaces-before-implementations — tests drive real seams (`build_guarded_client`, `search_and_crawl`, account repo), not internals
- [x] Budget posture — MockTransport + scripted resolver, no real network/DNS; no paid dependency introduced

## Notes
- Scope exclusions are correct: S8 real injection classifier (P10), S14 retention purge (P9/P11), S9
  denial-of-wallet gates (P11) are explicitly deferred and out of this `(T)` line — not gaps here.
- Follow-up (not blocking this task): the **PRE-GO-LIVE REVIEW** gate (locked, blocks any P11 cutover) still
  owes a GO/NO-GO on whether S1–S16 are genuinely done; the three deferred items above are its inputs. This
  verification advances but does not discharge that gate.
- Live-DB cascade result (548 passed, 1 heavy-ML importorskip) is the strongest available proof and matches
  the P2 skip-not-fail integration convention.
