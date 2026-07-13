---
name: project-security-privacy-posture
description: LOCKED security/privacy rulings (§7.2-7.6) — non-public backend + BFF httpOnly cookie, SSRF guard, untrusted-document rule, topic guardrail, denial-of-wallet, GDPR erasure/Art.9. The [SEC] block.
metadata:
  type: project
---

Locked 2026-07-13 with the owner; written into design §7.2–§7.6 + a **[SEC] block between P5 and P6** in
plan.md/tasks.md. The app is **branch-only, not live** — so these are ordered by **cost-to-unwind**, not
exposure.

**Locked rulings (gate on these):**
- **§6.12 Backend is not public.** Only the Next.js port is published; Postgres/Redis/FastAPI live on the private
  Docker network with **no host ports** (dev exposure → opt-in override). ✅ **DONE — SEC-03 (APPROVED):**
  `docker-compose.yml` now publishes only `3000`; dev exposure = `docker-compose.dev-ports.yml` (opt-in, NOT
  `override.yml` which auto-merges); `backend/Makefile` live-DB targets bring the DB up via the override.
  Bless this override-file naming pattern for future infra tasks. Frontend still uses `INTERNAL_API_URL=
  http://backend:8000` build ARG (blessed FIX-05). Follow-up for SEC-04: `docs/oauth-setup.md` OAuth callbacks
  still on `:8000` — must move to the `:3000` origin under the BFF rework.
- **§6.13 Session → httpOnly cookie via a Next.js BFF (Route Handlers), never `localStorage`.** Supersedes the
  P1–P3 Bearer-in-JS approach. Token never exists in JS (XSS-proof), OIDC callback sets the cookie (no token in
  the URL fragment). ⚠️ **Correct a common misreading:** a `rewrites()` pass-through is NOT enough — the browser
  still originates the call and carries the token, so the API stays internet-reachable *through* the proxy.
  **Network isolation does not make endpoints non-public; authN/authZ/rate-limits/guardrails stay load-bearing.**
- **§6.14 Untrusted content = ANY token the user did not type** — CV/OCR text, crawled pages, postings, snippets.
  Data, never instructions. Enforced **structurally**: fencing + no tool-call may be *initiated* by untrusted
  text + constrained-schema extraction + output guardrail strips echoes. (The old doc only said this of crawled
  pages — the asymmetry was the bug; a CV is a stranger's file run through OCR into the model context.)
- **§7.4 Topic guardrail** — see [[project-product-scope]].
- **§7.5 Denial-of-wallet is the most likely real attack:** guest limits are keyed on `session_id` and anyone can
  mint a fresh guest session → a script farms sessions and burns the free LLM quota. Needs per-IP guest-creation
  limits + a global daily budget breaker + a bot check. **P11 go-live gate.**
- **§7.6 Privacy:** durable `user_memories` must be **PII-redacted** and **free of GDPR Art. 9 special
  categories** (health/disability/ethnicity/religion — a career coach *will* receive these). `DELETE /api/me`
  (Art. 17, cascades every store) + `GET /api/me/export` (Art. 20) — neither existed. Traces/logs must be
  PII-redacted with retention (they'd otherwise hold full CV text).

**Known live code gaps at the time of writing (verify before citing):**
- `agents/web_searcher.py` fetches with `follow_redirects=True` and **no scheme/IP validation** → SSRF into the
  co-located `redis:6379` / `db:5432` or `169.254.169.254`. Highest-severity gap; must land **before P6**.
- `guardrails/heuristics.py` is a regex deny-list — an honest placeholder that stops nobody; real classifier is
  P10.

**Credit where due (do not "fix" these):** `SessionAuthenticator` checks the **live session record** on every
request, so logout genuinely revokes without a denylist. SSO-only + PKCE + minimal scopes is sound.

**Open decisions:** how aggressively to redact CVs before third-party inference calls (they go to HF Inference
today, unredacted) + Art. 13 disclosure; datastore durability on an ephemeral Space (self-host vs free managed
tier — "saved history" is otherwise a promise the architecture can't keep); retention periods.
