# Engineer report — P3-07-verify · Revision 1

## Summary
Delivered the **P3 phase-level exit-verification** proof as a single, citable integration module —
`backend/tests/test_p3_exit_verification.py` — that ties the already-built P3 building blocks
(P3-01 guest session, P3-02 SSO OIDC, P3-03 guest→account upgrade, P3-04 authZ + rate limits)
together and drives them **end-to-end through the real HTTP router stack with real, minted bearer
tokens**. This is a **verification-only** task: no product code, schema, or endpoints changed — one
new test file (6 tests), all of which actually run and pass with nothing stubbed but the LLM/tool
work and the datastore drivers (in-memory ports, no Redis/Postgres/HF/network).

The four plan.md P3 exit criteria are met, proven by the tests cited below (plan.md P3: *"guest and
logged-in flows work; guest→account upgrade carries the session; access control enforced"*).

**No gaps requiring a fix to a prior P3 task were found.**

## What makes this a real *exit* proof (vs. the per-task suites)
The per-task API suites verify each block in isolation and take a shortcut: they override
`require_auth` with a stand-in `CurrentUser`, or stub a single service. That proves the route logic
but **not** that a token the guest/SSO service actually mints will authenticate. This module closes
that seam: it wires **one** shared `InMemorySessionStore` behind a **real**
`SessionAuthenticator`, so `require_auth` verifies the **actual JWTs** minted by the guest/SSO/upgrade
services against live session records — exercising the full authN → authZ → rate-limit → route path.
Tokens are obtained the way a browser would (`POST /api/auth/guest`, SSO `login`→`callback` fragment)
and replayed as `Authorization: Bearer` on `POST /api/chat` / cancel.

## Files changed
- `backend/tests/test_p3_exit_verification.py` — **new.** 6 integration tests over the four exit
  criteria, plus two adjacent guards (unauthenticated → 401; logout revokes). Self-contained
  (own `_Harness` of shared in-memory stores + real services, a canned `_FakeChatService`, a
  recording `ConversationStore`, and a no-network `_MultiUserOIDCClient` that resolves a distinct
  user per authorization code so two real accounts can be minted for the cross-user test).

No other files touched.

## Criteria → tests (all pass)
1. **Guest flow** — `test_guest_flow_chats_to_limit_then_upgrade_prompt`: real guest JWT from
   `POST /api/auth/guest` authenticates `POST /api/chat` for 10 messages; the 11th is denied `429`
   with an upgrade-prompting `detail` (`"Sign in..."`) + `Retry-After`. (`..._without_token...` also
   asserts a tokenless call is `401`.)
2. **SSO flow (mocked provider)** — `test_sso_flow_issues_token_that_authenticates_a_protected_route`:
   `login`→`callback` mints a decodable `role="user"` JWT bound to the session; it then actually
   authenticates `POST /api/chat` (`200`), and the turn is handed the **token-derived** `user_id`
   (never a client-sent field, §7 AuthZ). (`test_logout_revokes_the_sso_session` proves the same
   token stops resolving after logout → `401`.)
3. **Upgrade-preserves-session** — `test_upgrade_preserves_session_and_begins_persisting`: guest
   chats (seeded memory) → mints ticket → completes SSO with it → lands back in the **same**
   `session_id` (record promoted guest→user; prior transcript backfilled to the durable store), and
   the **promoted user token continues chatting on that same session** (`200`, invoked with the new
   `user_id`).
4. **Cross-user access denied** — `test_cross_user_access_is_denied`: two real user sessions A and B;
   A's token → B's session on chat = `403`, on cancel = `403` (closes the P1 "anyone can cancel"
   gap), A's own session still `200`, and the cross-user attempts **never reached the service** (only
   A's own session appears in the fake service's invocations — rejected at the authZ boundary).

## Key decisions
- **Real authenticator over one shared session store** (not `require_auth` override) — the whole
  point of a *phase-exit* test is to prove the pieces compose, so the value-add over P3-01..P3-06's
  suites is exercising the genuine token-mint → token-verify path. (§7.1 backend-owned session JWT.)
- **Per-authorization-code identity in the OIDC fake** (`_MultiUserOIDCClient`) — the shared
  `FakeOIDCClient` in `tests/fakes.py` always returns one fixed `sub`, which cannot produce the two
  distinct users the cross-user criterion needs. A local no-network client maps `code-A`/`code-B` to
  distinct `(sub,email)`; everything else (PKCE/state mechanics) matches the shared fake. Kept local
  to this module rather than widening the shared fake (YAGNI — no other suite needs multi-user).
- **Fake chat service, not the real one** — the P3 exit criteria are about the auth/session
  boundary; the model⇄tools loop and logged-in persistence are P1/P2 concerns already verified
  (P1-09, P2-08). The fake records `(session_id, user_id)` so the tests can assert the router handed
  the turn the token-derived identity. "Now persisting" (criterion 3) is proven by the upgrade
  backfill (`_RecordingConversationStore.persisted`), which is the actual mechanism by which an
  upgraded conversation *begins* persisting.
- **Status asserted without draining the SSE body** — rate-limit/authZ decisions happen in the
  handler *before* the stream opens, so the response status is authoritative immediately (same idiom
  as the existing `test_authz_ratelimit_api.py`).

## How to verify
```bash
cd backend
.venv/bin/python -m pytest tests/test_p3_exit_verification.py -v   # the 6 exit tests
.venv/bin/python -m pytest -q                                      # full suite
.venv/bin/ruff check tests/test_p3_exit_verification.py
.venv/bin/mypy tests/test_p3_exit_verification.py
```

## Tests (final step — mandatory)
- `pytest tests/test_p3_exit_verification.py -v` → **6 passed** (all four criteria + 2 guards).
- `pytest -q` (full backend suite) → **198 passed, 43 skipped in 3.11s** (the 43 skips are the
  live-Postgres integration tests, skipped with no DB reachable — unchanged from the pre-task
  baseline of 192 passed / 43 skipped; this task adds exactly the 6 new passing tests).
- `ruff check` → **All checks passed!** · `mypy` → **Success: no issues found**.
- No failures to root-cause.

## Self-check
- [x] Meets acceptance criteria (all four flows covered by automated tests; full suite green).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (test-only; drives the real
      router/service/port layering through HTTP, no driver reached).
- [x] Tests/lints pass (pasted above).
- [x] No new endpoints/features introduced (verification only); no gaps found needing a prior-task fix.
