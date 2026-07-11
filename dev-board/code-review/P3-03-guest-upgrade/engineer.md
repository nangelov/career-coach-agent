# Engineer report — P3-03-guest-upgrade · Revision 1

## Summary
Implemented guest → account upgrade that **preserves the active session** (§4: *"Upgrade-to-account
preserves current session"*). When a guest completes SSO, the *same* session carries over to the
new account rather than starting fresh: the guest's `session_id` is kept (so the live Redis
conversation memory and the client's in-progress conversation continue seamlessly), its session
record is promoted in place from `role="guest"` to `role="user"`, and its prior transcript is
backfilled into Postgres so the conversation *begins persisting* like any logged-in session.

The binding between "which guest session upgrades" and the OIDC flow is made **safe** (acceptance
#3) via a server-minted, opaque, single-use, short-lived **upgrade ticket** — the client never
supplies a raw guest id. Flow:

1. Guest (holding a verified guest token) calls `POST /api/auth/upgrade` → gets an `upgrade_ticket`
   bound *server-side* to that verified guest `session_id`.
2. Browser navigates to `GET /api/auth/login/{provider}?upgrade_ticket=<ticket>`. `begin_login`
   **consumes** the ticket (single-use), resolves it to the guest session id, and stashes that id
   in the server-side OAuth transaction record — so it survives the provider round-trip without any
   guest id / token ever appearing in a URL the browser could tamper with.
3. `GET /api/auth/callback/{provider}` completes SSO, upserts the user, then upgrades: same
   `session_id` kept, record promoted, transcript backfilled. The user token (`role="user"`,
   `sid == guest session_id`) is delivered in the redirect fragment as before.

Layering respected: Router (`api/auth.py`, thin) → Service (`services/guest_upgrade.py`,
`services/auth.py`) → ports (`UpgradeTicketStore`, `SessionStore`, `SessionMemory`,
`ConversationStore`) with the Redis adapter in `repositories/`. No datastore driver touched in a
service.

## Files changed
New:
- `app/services/upgrade_ticket_store.py` — `UpgradeTicketStore` ABC port + `InMemoryUpgradeTicketStore`
  (single-use ticket → guest session id; same interface-before-impl idiom as `OAuthStateStore`).
- `app/services/guest_upgrade.py` — `GuestUpgradeService`: `create_ticket` / `resolve_ticket` (the
  safe binding) + `upgrade` (promote record in place, keep same session id, best-effort backfill).
  `_pair_turns` reduces the live transcript to clean user↔assistant turns (tool scaffolding dropped).
- Tests: `tests/test_upgrade_ticket_store.py`, `tests/test_guest_upgrade_service.py`,
  `tests/test_guest_upgrade_api.py`.

Modified:
- `app/schemas/auth.py` — added `UpgradeTicketResponse` (the `POST /api/auth/upgrade` body).
- `app/services/oauth_state_store.py` — `OAuthStateRecord` gains optional `upgrade_session_id`
  (carries the guest session across the provider round-trip, server-side only).
- `app/services/auth.py` — `SsoAuthService` takes an optional injected `GuestUpgradeService`;
  `begin_login` accepts/consumes an `upgrade_ticket`; new `_resolve_session` upgrades in place when
  the state carries an `upgrade_session_id`, else mints a fresh session (unchanged P3-02 behavior).
- `app/repositories/redis.py` — `RedisUpgradeTicketStore` (prefix `upgrade:ticket`, single-use
  `pop`, reuses the existing `StoreRedis` seam).
- `app/api/auth.py` — `POST /api/auth/upgrade` (guest-only, else 409), `get_guest_upgrade_service`
  dependency, `upgrade_ticket` query param on `GET /login/{provider}`.
- `app/app_state.py` — `GUEST_UPGRADE_SERVICE` state key.
- `app/bootstrap.py` — `build_guest_upgrade_service`; wired into `build_sso_auth_service`.
- `app/config.py` — `UPGRADE_TICKET_TTL_SECONDS` (default 300s / 5 min).

## Key decisions
- **Keep the same `session_id` (in-place promotion), don't re-key** (acceptance #1). The Redis
  working memory is keyed on `session_id`; keeping the id means the conversation carries over with
  zero data movement and the client stays in the same conversation. The record is overwritten
  `guest → user` with `user_id` + the logged-in TTL, preserving the original `created_at`.
- **Server-minted single-use upgrade ticket, not a client-supplied guest id or a token-in-URL**
  (acceptance #3, §7.1 posture). The login endpoint is a browser GET redirect (can't carry an auth
  header), so the ticket decouples "authenticated guest proves ownership" (`POST /api/auth/upgrade`
  with the guest bearer) from "browser navigation to login" (opaque ticket in the URL). The ticket
  carries no secret (only names a guest session), is single-use (`pop`), and short-lived — consistent
  with the design's choice to keep the result token out of query params. This closes the "trust a
  client-supplied guest id" hole.
- **Backfill by reusing `ConversationStore.persist_turn`, not by extending the port.** The guest's
  prior user↔assistant turns are persisted via the exact same method a live logged-in turn uses, so
  durable history is byte-identical in shape (get-or-create session + conversation, tool scaffolding
  dropped). This avoided adding an abstractmethod that would have broken every existing
  `ConversationStore` fake (DRY + KISS).
- **Backfill is best-effort; the upgrade still succeeds if it fails** (acceptance #2 mechanism). A DB
  failure is logged and stops the backfill but never blocks the login — the conversation still lives
  in Redis and *future* turns persist because the session is now `role="user"` with `user_id`. Mirrors
  the chat service's best-effort persistence posture.
- **`upgrade()` returns `False` (→ mint fresh session) when there's nothing to upgrade** — guest
  session expired before callback, or already promoted (a replay). Graceful degradation: the user
  still logs in, just without carry-over. This also makes double-upgrade safe.
- **No cross-contamination** (acceptance #4): each ticket binds to exactly one guest session id; each
  OAuth state carries one `upgrade_session_id`; concurrent upgrades use distinct session ids →
  distinct Redis memory keys + distinct Postgres sessions. Covered by a concurrent-upgrade test.
- **`GuestUpgradeService` is a separate collaborator, not folded into `SsoAuthService`** (SoC).
  `SsoAuthService` stays focused on OIDC and delegates the carry-over; the service is injected as an
  *optional* dependency so existing SSO tests (which construct it without upgrades) are unaffected.

## How to verify
- `cd backend && .venv/bin/python -m pytest tests/test_guest_upgrade_api.py tests/test_guest_upgrade_service.py tests/test_upgrade_ticket_store.py -q`
- End-to-end (no Redis/Postgres/network — the API test drives the full Router→Service path over
  shared in-memory stores + a scripted OIDC client): `POST /api/auth/guest` → seed a conversation →
  `POST /api/auth/upgrade` (guest bearer) → `GET /login/google?upgrade_ticket=…` (302) →
  `GET /callback/google?code=…&state=state-1` (302) → the fragment's `session_id` equals the guest
  session id, the record is `role="user"`, and the prior turn is backfilled to the durable store.

## Tests (final step — mandatory)
- `.venv/bin/ruff check app tests` → All checks passed. `ruff format` → clean (2 new test files
  auto-formatted during authoring).
- `.venv/bin/mypy app tests` → only the **2 pre-existing** errors remain
  (`tests/test_llm_router.py:309` unused-ignore, `tests/test_message_id.py:71` FakeRegistry
  arg-type) — both in files I did not touch (confirmed present at HEAD in the P3-01/P3-02 reports).
  All new/changed files type-clean under `--strict`.
- `.venv/bin/python -m pytest -q` → **169 passed, 41 skipped** (skips = live-DB integration suites,
  expected without a reachable Postgres). New P3-03 tests: **15 passed** (7 service + 4 API + 4
  ticket store). Was 154 passed before this task.
- No test failures. No test weakened/deleted.

## Self-check
- [x] Meets acceptance criteria: guest chats → login → SSO → same conversation (same `session_id`,
  record promoted); post-upgrade the conversation persists to Postgres (prior turns backfilled via
  the P2 persistence path, future turns via the existing logged-in path); safe binding via a
  server-minted single-use upgrade ticket (no client-supplied guest id trusted); tests cover
  history-preserved-on-upgrade and no cross-contamination between concurrent unrelated upgrades.
- [x] No secrets committed (upgrade ticket carries no secret; signing key still env/Space-secret
  only). Router→Service→Repository layering respected; interfaces before implementations
  (`UpgradeTicketStore` port before the Redis adapter).
- [x] Tests/lints pass (see above); pre-existing mypy noise called out, not introduced.
