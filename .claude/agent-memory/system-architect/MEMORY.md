# Memory index

- [v2 locked stack](project-v2-locked-stack.md) — the 9 pre-work decisions (GLM-5.2, Qwen3-Embedding-8B dim=4096, LangMem, self-host, guest 10msg+1doc, resume); all 9 now LOCKED (#8 = silent-but-viewable/deletable memory, opt-out)
- [LLM layer seam](project-llm-layer-seam.md) — blessed llm/ pattern (P1-01): LLMClient ABC + first-party types/errors, single client max_retries=0, failover/resume only in router.py (P1-02)
- [Frontend path](project-frontend-path.md) — RESOLVED P0-13: v2 now at canonical §8 frontend/ (renamed from frontend-v2/); v1 CRA in legacy-code/; package.json name still -v2 (cosmetic)
- [Frontend SSE pattern](project-frontend-sse-pattern.md) — blessed P1-08 layering: transport in lib/, UI in components/, thin app/; typed union mirrors backend schemas/chat.py; POST-SSE via fetch not EventSource
- [ORM models layout](project-orm-models-layout.md) — blessed P2-03: repositories/models/<group>.py subpackage + identity schema rulings (no password, message_id String(32), feedback SET NULL) for P2-04/05 consistency
- [Hybrid search](project-hybrid-search.md) — blessed P2-06: RRF blend (caller-configurable weights), injectable encoder seam, vector-only user_memories, repo→llm injected not imported; for P2-exit/P4/P5
- [Conversation persistence](project-conversation-persistence.md) — blessed P2-07: ConversationStore port + Postgres adapter, interim user_id seam (non-authZ, P3), best-effort persist-after-terminal + Redis-empty rehydrate, guests Redis-only
- [Phase-exit verification](project-phase-exit-verification.md) — blessed P2-08 pattern for (T) tasks: tests-only, drive real seams, cite prior tests + close only genuine gaps, skip-not-fail live-DB, no product surface
- [CI posture](project-ci-posture.md) — FIX-01/P0-09: live-DB integration deferred out of CI (skip-not-fail, expected-by-design), curated light install must list required libs (pgvector bug), DRY follow-up on duplicated list
- [CR-01 audit rulings](project-cr01-audit-rulings.md) — rev 2 APPROVED, A3-A8 closed; blessed bootstrap.py root + AppStateKeys + _mixins; P3: remove client user_id, warm Redis eagerly
- [Auth/session seam](project-auth-session-seam.md) — blessed P3-01+P3-02: security/ pkg, generic SessionStore, uniform JWT; P3-02 = security/oidc OIDCClient port, PKCE S256, user-sessions Redis-anchored (not §4 PG, accepted), userinfo not id_token, logout=delete record; A10→P3-04
- [Guest upgrade](project-guest-upgrade.md) — blessed P3-03: in-place same-session_id promotion + transcript backfill at upgrade boundary (§4-sanctioned, not a violation) + server-minted single-use upgrade ticket (no client-supplied guest id)
- [Admin authz](project-admin-authz.md) — blessed P3-05: is_admin column (not JWT claim, per-request DB check), require_admin composes on require_auth (401 vs 403), lookup on single UserStore port, no self-service escalation, read-only FeedbackReader
- [AuthZ + rate limits](project-authz-ratelimit.md) — blessed P3-04: centralized authorize_session_access (session==token.sid), identity from token not body, RateLimiter port + Redis fixed-window, guest Decision-8 caps; P5 follow-up = repo-level owner filter for relational rows
