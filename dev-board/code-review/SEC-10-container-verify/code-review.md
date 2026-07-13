# Code review — SEC-10-container-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| — | — | — | No defects. Verification-only task, no code changes; all reported claims are internally consistent and corroborated by the source. | — |

## Notes
Verification-only task (no code touched — confirmed: the modified files in `git status` are the
SEC-01..09 deliverables reviewed under their own tasks, not new churn from this pass). I spot-checked
every live claim against the actual code rather than re-running the stack; all hold up:

- **Port lockdown (SEC-03):** `docker-compose.yml` publishes only `frontend` `3000:3000`; `db`, `redis`,
  `backend`, `worker` publish no host port (host ports are opt-in via `docker-compose.dev-ports.yml`).
  The reported `curl :8000 refused` / `:5432`/`:6379` refused is exactly what this compose file produces.
- **Guest cookie (SEC-04/06):** `app/api/auth/guest/route.ts` returns a token-free body
  (`sessionId`/`role`/`expiresAt` only — the `access_token` goes into the cookie via `setSessionCookie`,
  never the response). `lib/bffProxy.ts::setSessionCookie` sets `httpOnly:true, sameSite:lax, path:/,
  maxAge=exp`; `secure` is production-only, so the reported `Secure` flag being present is a good
  consistency signal that a real *production* container image was exercised (not the dev server). Consent
  default is fail-closed (`consent = body?.consent === true`, missing/invalid body → false → backend 400).
- **Authorization-injection proof — the reasoning is sound and actually stronger than the task asked.**
  The engineer correctly rejected `GET /api/auth/session` as proof (it only local-decodes the cookie via
  `clientSessionState`, never hits the backend — verified) and instead used `GET /api/profile` through the
  catch-all `app/api/[...path]/route.ts` → `proxyRequest`, which strips any client `authorization`/`cookie`
  and injects `Authorization: Bearer <token>` from the cookie server-side. The 200-with-cookie /
  401-without-cookie delta genuinely demonstrates server-side injection against the live backend: the
  browser never carries a Bearer, so the only path to an authenticated backend request is the proxy's
  cookie→Bearer conversion. This is a legitimate, non-hand-wavy proof.
- **SSE / network-egress limitation — honestly reported, not swept under the rug.** The reported failure
  (`ConnectError: No address associated with hostname` → `APIConnectionError` → `LLMAllModelsFailedError`,
  both failover models) is a genuine sandbox DNS/egress boundary, not a code defect, and the observed
  graceful-fallback `token` + `error` `done` frame is the designed mid-stream guardrail (§7.2). SSE
  plumbing is legitimately verified end-to-end up to the model-call boundary; the boundary is disclosed
  plainly per the design's own honesty standard (§6.17). OAuth-callback gap is likewise disclosed and
  explicitly out of this task's scope.
- Teardown without `-v` (volumes preserved) matches the documented P2 precedent in `backend/Makefile`.

Real commands are the project's real ones (`uv run --no-sync pytest` per Makefile `test`; frontend `jest`).
The 54 pytest skips = live-DB integration tests skipping without a reachable Postgres — expected on the host.
