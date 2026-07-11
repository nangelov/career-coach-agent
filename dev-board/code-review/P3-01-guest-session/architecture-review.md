# Architecture review — P3-01-guest-session · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Guest endpoint in `api/auth.py` (guest + SSO + session JWT) | `api/auth.py` thin router, `POST /api/auth/guest`, no repo/security imports beyond the `get_*` dep + response schema | Conforms. |
| A2 | §8 structure | Business logic in `services/`, DB access in `repositories/`, models in `schemas/` | `services/auth.py` (GuestAuthService), `repositories/redis.py` (RedisSessionStore adapter), `schemas/auth.py` (SessionRecord/response/role) | Conforms. |
| A3 | §8 structure | Token codec home not explicitly listed in §8 | New leaf pkg `app/security/tokens.py` (framework/datastore-free JWT primitive) | Extension, not in §8 tree. Blessed as SoC-correct (see Notes N1). P3-02 OIDC/PKCE helpers should land in `security/` or `api/auth.py`, not `services/`. |
| A4 | Layering (Router→Service→Repo) | Router thin; service on ports; no driver in service | Router → `GuestAuthService` → `SessionStore` + `SessionTokenCodec` ports; Redis adapter behind `StoreRedis` Protocol; wired only in `bootstrap.py` | Conforms — clean; service touches no driver. |
| A5 | Interfaces-before-implementations | Real seams for swappable stores | `SessionStore` ABC (`InMemory` test double + `RedisSessionStore` adapter), same idiom as SessionMemory/CancelRegistry | Conforms. Codec is a concrete primitive (acceptable — no impl to swap). |
| A6 | §4 data ownership | Guests Redis-only, TTL, no Postgres `conversations`/`messages` | `build_guest_auth_service` wires **no** Postgres; record persisted to Redis with `GUEST_SESSION_TTL_SECONDS` (24h); no conversation store touched | Conforms. |
| A7 | §6.2/§7.1 backend-owned session JWT | Backend mints its own short-lived session JWT; no passwords | HS256 via `SessionTokenCodec`, `exp` essential-validated, key from `JWT_SECRET_KEY`; empty-secret fails at construction | Conforms. |
| A8 | §7.1 / §9 uniform token shape | Coordinate token shape with P3-02 so frontend treats guest/user uniformly | Claims `sub/role/sid/iat/exp`, `role ∈ {guest,user}`; guest `sub==sid==session_id`; P3-02 sets `sub=users.id`, `role=user`. Generic `SessionRecord`/`SessionStore` reused (no second type) | Conforms — good forward-coordination. |
| A9 | P3-04 rate-limit handle | Session carries a Redis-keyable handle for the 10-msg/1-upload limit | `session_id = uuid4().hex` (32 chars, within 64-char `sessions.id`/`ChatRequest.session_id` bound); record TTL ≥ token lifetime so counters survive token refresh | Conforms. |
| A10 | Phase fit | No SSO/OIDC, no rate-limit enforcement in this task | Neither present; only the session handle + uniform token seam laid down | Conforms. |
| A11 | §4 one shared Redis pool | Acquire via repository-layer provider, one bounded pool | `_shared_redis_client(app)` extracted in `bootstrap.py`; chat + auth reuse the one `RedisConnectionProvider` on `app.state` (fixes latent double-pool) | Conforms — strengthens the CR-01 single-composition-path ruling. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — one blessed extension (`security/`, N1)
- [x] Honors locked decisions (no ReAct parser touched; Postgres+Redis only, guest Redis-only; SSO-only/no-passwords; backend-owned short-lived session JWT)
- [x] Interfaces-before-implementations (`SessionStore` ABC + adapter; `SessionTokenCodec` primitive; `StoreRedis` Protocol seam)
- [x] Budget posture respected (free/OSS/self-hosted; joserfc/redis, no paid service)

## Notes
- **N1 (blessed extension):** `app/security/` is not in the §8 tree, but a framework/datastore-free auth primitives package is SoC-correct — it keeps `api/auth.py` thin and `services/auth.py` free of JWT crypto, and gives P3-02's verify dependency a single home. Cheap to relocate; recorded as an accepted pattern. Keep P3-02 OIDC/PKCE state + verify dependency consistent (in `security/` or the thin router), not smeared into `services/`.
- **N2 (joserfc vs `authlib.jose`):** the design mandates **Authlib** for the OIDC *flow* (P3-02), not for JWT minting. `authlib.jose` is deprecated in favour of joserfc (same maintainer); authlib itself pins `joserfc>=1.6.0`, so it is a guaranteed transitive dep, not a coincidental one. Choice is consistent with design intent — not a deviation. Minor import-hygiene follow-up: declare `joserfc` as a **direct** dependency in `pyproject.toml` (a load-bearing import should not rely on another package's transitive pin). Non-gating.
- **N3 (mild YAGNI, accepted):** `decode()` and `SessionStore.get()` are unused by the guest-create path but are part of a coherent seam P3-02 consumes immediately, and `decode` is round-trip-tested here. Building a complete port (not speculative generality) with P3-02 landing next — acceptable.
- **N4 (carry-forward, not this task):** CR-01 A10 — remove the client-trusted `ChatRequest.user_id` interim field once the verified JWT populates identity — remains **open**; belongs to the P3 authz/session-verify task, not P3-01. Flagging so it is not lost.
- **N5 (P3-02 note, not gating):** §4 `sessions` is a Postgres table for logged-in users; the generic `SessionRecord`/`SessionStore` will need a Postgres adapter (or a documented Redis-anchored decision) for `role=user`. The port is generic enough to absorb this; resolve it in P3-02.

## Verdict: APPROVED
