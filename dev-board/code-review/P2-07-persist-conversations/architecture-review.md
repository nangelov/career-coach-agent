# Architecture review — P2-07-persist-conversations · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | port in `services/`, DB adapter in `repositories/` | `ConversationStore` ABC in `app/services/conversation_store.py`; `PostgresConversationStore` in `app/repositories/conversation_store.py` (own module, not swelling `postgres.py`) | none |
| A2 | Layering (Router→Service→Repo) | service depends on port; DB access confined to repo; router only threads a field | `ChatService` depends on `ConversationStore` port; adapter is sole DB toucher; `api/chat.py` only threads `payload.user_id` into `stream_turn` | none |
| A3 | §4 "Guests get NO persisted history" | `user_id is None` → Redis-only, nothing in Postgres | `_persist_turn`/`_load_prior` short-circuit when `user_id` falsy or store `None`; guest path byte-for-byte P1 | none |
| A4 | Interfaces-before-implementations | ABC precedes concrete adapter; swappable seam | `ConversationStore(ABC)` with `persist_turn`/`load_history`; concrete Postgres adapter satisfies it; fakes in tests | none |
| A5 | §4 single shared pool, no ad-hoc connections | acquire via `PostgresConnectionProvider` from P2-01 | adapter uses `self._provider.session()`; provider sourced from `app.state.pg_provider` at composition root (`build_chat_service`) | none |
| A6 | P2-03 schema reuse | `sessions`/`conversations`/`messages`, `message_id` natural key, role check, cascades | maps `Session`/`Conversation`/`Message`; get-or-creates session+conversation; stamps turn `message_id` on assistant row (§5.5) | none |
| A7 | Interim identity seam (P1-04 precedent) | optional documented `user_id` stand-in, not an authZ boundary | `ChatRequest.user_id: str \| None` documented as P3-JWT stand-in; adapter/port docstrings state the P3 gap | none |
| A8 | §5.5 stable feedback id | turn `message_id` survives to durable store | assistant answer (incl. partial-on-cancel) persisted carrying the turn's `message_id`; user message gets auto id | none |
| A9 | Locked stack (Postgres+Redis only, no LangGraph/SSO creep) | no premature coupling, no new datastore | pgvector/Postgres + Redis only; no MongoDB; no LangGraph; no auth endpoint built | none |
| A10 | Restart rehydration (§4 saved history) | account history survives Redis loss | `_load_prior` falls back to `load_history` only when Redis empty AND `user_id` set; integration + restart-sim tests | none |
| A11 | Non-blocking best-effort persist | persist after terminal event, failures never break stream | persist after `done`/`cancelled` yielded; both persist + rehydrate wrapped best-effort (logged, swallowed) | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo)
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only not violated — interim `user_id` explicitly documented as non-authZ P3 stand-in; in-process embeddings untouched)
- [x] Interfaces-before-implementations (`ConversationStore` ABC before adapter, mirroring `SessionMemory`/`CancelRegistry`)
- [x] Budget posture respected (self-hosted Postgres, no managed/paid tier)

## Notes
Design-conformant; the following are logged follow-ups, not gates:

- **N1 (minor, cross-task) — `session_id` length ceiling.** `ChatRequest.session_id` allows `max_length=200`
  but `Session.id`/`Conversation.session_id`/FKs are `String(64)` (P2-03). Real ids are 36-char
  `crypto.randomUUID()` (P1-08), so this never triggers in practice; for a logged-in user a >64-char
  `session_id` would fail the insert (caught best-effort, so no user-visible break). Worth aligning the
  `ChatRequest.session_id` bound to 64 in a future pass, or documenting the divergence — not blocking.
- **N2 (minor, forward-looking) — ordering without a sequence column.** `load_history` orders by
  `(created_at, role_rank)` with one wall-clock timestamp per turn. This is a sound pragmatic choice that
  avoids a P2-03 schema change and correctly disambiguates the user/assistant pair within a turn. It leans on
  distinct per-turn `created_at` values (each turn is its own committed transaction, microsecond precision).
  When P4's multi-agent trace/`trace` JSONB work lands, consider an explicit per-conversation ordinal so
  ordering is not timestamp-dependent. Acceptable for this phase.
- **N3 (context) — thinner rehydrated transcript.** Only user + final/partial-assistant messages are durably
  stored (tool round-trips deliberately omitted), so post-restart context is a clean user↔assistant
  transcript rather than the full live working memory. Intentional and consistent with §4's "ordered
  messages" framing; noted so a future P4 trace-persistence task is aware the durable store is intentionally
  lossy on tool scaffolding.
