# Code review — P3-02-sso-oidc · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/security/oidc.py:188, backend/app/services/oauth_state_store.py:44 | A `nonce` is generated and persisted in the OAuth-state record but never validated — identity is resolved via the `userinfo` endpoint (no id_token/JWKS), so the nonce is a dead security artifact. | Either drop the `nonce` field, or leave a `# reserved for future id_token validation` comment so a later reviewer doesn't assume it is load-bearing. Non-blocking. |
| C2 | minor | backend/app/api/auth.py:112-118 | The callback declares `code` and `state` as required `Query(...)`. When a provider redirects back with `?error=access_denied&state=...` (user declines consent), FastAPI returns a raw `422`, not a graceful redirect to the frontend. This is a UX gap, not a security issue (correctly covered by `test_callback_missing_params_422`). | Optionally accept an `error: str \| None = None` query param and redirect to `OAUTH_POST_LOGIN_REDIRECT` with an error indicator. Defer is acceptable. |
| C3 | minor | backend/pyproject.toml:20 | `joserfc` is imported directly (`security/tokens.py`) but only declared transitively via `authlib>=1.3.0`; no explicit pin. Pre-existing from P3-01 (tokens.py is a P3-01 file, unchanged here) — out of P3-02 scope, noted for follow-up. | Add an explicit `joserfc>=1.6.0` to `dependencies` since the signing path imports it directly. |

## Notes
Security posture checked and sound — this meets the task's security bar:
- **PKCE (S256):** fresh `code_verifier` per attempt, challenge sent to the provider, verifier stored server-side and passed on exchange; asserted by `test_authorization_request_has_pkce_and_minimal_scopes` (`code_challenge`, `code_challenge_method=S256` in the URL). A leaked client id alone cannot complete a flow.
- **CSRF / replay:** `state` is stored server-side and consumed single-use via `pop` (get-then-delete); `complete_login` also verifies `record.provider == provider`. Replay/forged/mismatched-provider state → `400`. `redirect_uri` used at exchange is the stored one, matching what was authorized.
- **JWT:** HS256, `algorithms=[configured]` pinned on decode (blocks alg-swap/`alg:none`), `exp` marked essential and validated, claims re-validated through the typed `SessionClaims` (unknown `role` rejected), all joserfc/validation errors wrapped in codec-owned `InvalidSessionToken`; empty secret fails at construction. Verified by `test_session_token`.
- **No passwords:** `PostgresUserStore.upsert` writes only `provider/sub/email/display_name` via `ON CONFLICT (provider, sub) DO UPDATE ... RETURNING id`; there is no credential column.
- **Secrets:** all client ids/secrets, `JWT_SECRET_KEY`, redirect base come from `pydantic-settings` (env/Space secrets); `.env.example` holds placeholders only; nothing hard-coded.
- **Identity resolution** via `userinfo` over TLS (not id_token/JWKS) is a documented deliberate simplification; safe because identity is keyed on `(provider, sub)`, so `email_verified` is not load-bearing (no unverified-email takeover). Token delivered in the redirect **fragment** to avoid server-log/Referer leakage.
- **Logout:** deletes the Redis session record; `require_auth` needs a live record → immediate revocation without a denylist. `test_logout_revokes_session` proves the post-logout `401`.

Acceptance criteria — all met: login `302`→consent (PKCE + minimal scopes), callback exchanges/verifies/upserts/mints, short-lived config-signed JWT + reusable `require_auth`, `POST /logout` ends session, config-derived redirect URIs, tests pass with no real credentials, `docs/oauth-setup.md` present.

Layering respected (thin Router → Service → ports → repository/security adapters); interfaces-before-implementations throughout; testable via `httpx.MockTransport` + in-memory fakes with no live network.

Verification run locally: the 8 P3-01/P3-02 auth suites → **41 passed**; `ruff check` clean; `mypy app tests` → only the **2 pre-existing** errors (`test_message_id.py:71`, `test_llm_router.py:309`) in files untouched by this task — no new type errors introduced. Engineer's report is accurate.
