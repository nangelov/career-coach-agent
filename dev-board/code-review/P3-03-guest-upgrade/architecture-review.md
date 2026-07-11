# Architecture review — P3-03-guest-upgrade · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §4 "Upgrade-to-account preserves current session" | Same active session carried into the new account, not a blank one | `GuestUpgradeService.upgrade` keeps the **same `session_id`**, promotes the record in place (`guest`→`user`, preserves `created_at`), leaves Redis working memory untouched under the same key | Conforms |
| A2 | §4 "no history saved" for guests / persist once logged-in | On upgrade the user is no longer a guest, so the transcript must begin persisting to Postgres | `_backfill` replays the prior user↔assistant turns through `ConversationStore.persist_turn`; the promoted record (`role=user`, `user_id`) makes future turns take the logged-in persistence path | Conforms — backfilling at upgrade is the correct reading of §4 (the guest-only-in-Redis rule ends the moment the account exists) |
| A3 | P2-07 persistence pattern ([[project-conversation-persistence]]) | Reuse the durable seam; durable store intentionally lossy on tool scaffolding | Backfill reuses `persist_turn` (no port extension); `_pair_turns` drops tool-call scaffolding/results, keeps user + final-assistant turns — byte-identical shape to a live logged-in turn | Conforms |
| A4 | §8 target structure | Port in `services/`, adapter in `repositories/`, thin router in `api/`, wiring in `bootstrap.py`, schema in `schemas/` | `services/upgrade_ticket_store.py` (ABC+fake) & `services/guest_upgrade.py`; `RedisUpgradeTicketStore` in `repositories/redis.py`; `POST /api/auth/upgrade` thin in `api/auth.py`; `build_guest_upgrade_service` in `bootstrap.py`; `UpgradeTicketResponse` in `schemas/auth.py` | Conforms |
| A5 | Layering Router→Service→Repository | Services touch no driver | `GuestUpgradeService` & `SsoAuthService` depend only on ports (`UpgradeTicketStore`, `SessionStore`, `SessionMemory`, `ConversationStore`, `OAuthStateStore`); router imports only services/schemas/deps | Conforms |
| A6 | Interfaces-before-implementations | Real swappable seam | `UpgradeTicketStore` ABC + `InMemory` double + Redis adapter — same idiom as `SessionStore`/`OAuthStateStore` ([[project-auth-session-seam]]) | Conforms |
| A7 | §7.1 auth posture / safe binding (acceptance #3) | No client-supplied guest id trusted; no secret/token in a URL | Server-minted opaque single-use `uuid4().hex` ticket bound server-side to the **verified** guest `session_id` (`POST /upgrade` gated by `require_auth`, guest-only else 409); ticket consumed in `begin_login`, guest id stashed server-side in the OAuth transaction — never in a browser-visible URL | Conforms |
| A8 | Locked stack (Postgres+Redis only, SSO-only) [[project-v2-locked-stack]] | No new datastore/provider; Redis-anchored sessions | Ticket store on the shared Redis pool; session promotion on `RedisSessionStore` (blessed Redis-anchored user session, P3-02); backfill only to Postgres via the shared PG pool | Conforms |
| A9 | Phase fit / non-goals | Rate-limit carry-over is P3-04 | Upgrade re-anchors only the session record + history; touches no rate-limit counters. Post-upgrade `role=user` naturally exits guest limiting | Conforms |
| A10 | Composition-root singularity ([[project-cr01-audit-rulings]]) | One shared Redis pool / one composition path | All three stores built off `_shared_redis_client(app)`; `build_sso_auth_service` composes `build_guest_upgrade_service` — single wiring path, optional PG store degrades cleanly | Conforms |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repository)
- [x] Honors locked decisions (Postgres+Redis only; SSO-only; Redis-anchored user session per P3-02; no ReAct parser touched)
- [x] Interfaces-before-implementations (`UpgradeTicketStore` port before Redis adapter)
- [x] Budget posture respected (no paid services; only a new TTL config `UPGRADE_TICKET_TTL_SECONDS`)

## Notes
- **Best-effort backfill is design-consistent, not a gap.** A DB failure logs, stops the backfill, and never blocks login (record still promoted → future turns persist). Mirrors the blessed P2-07 best-effort persistence posture. Graceful `upgrade()==False` (guest session lapsed / replay / double-upgrade) → fresh session mint is correct degradation.
- **Backfill idempotency / `conversation_id=None` per turn is a correctness question for the code-reviewer**, not an architecture gate: each `persist_turn(conversation_id=None)` relies on get-or-create resolving the *same* conversation for the session across successive calls. Design-shape is fine; the code-reviewer owns verifying no duplicate conversations/turns arise.
- **Follow-up dependency on A10 (open, → P3-04):** for *future* post-upgrade turns to persist, the chat path must treat the session as logged-in. Today that still rides the interim client-supplied `ChatRequest.user_id` seam ([[project-conversation-persistence]]); once A10 derives identity from the verified token this becomes automatic. Not this task's scope — the backfill already guarantees the *prior* transcript persists regardless. Flagging so P3-04 closes the loop.
- Ruling recorded to memory: backfilling a guest's transcript **at the upgrade boundary** is the sanctioned reading of §4 (not a "guests get persisted history" violation), and in-place same-`session_id` promotion (no re-key) is the blessed carry-over mechanism.
