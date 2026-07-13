# Task SEC-01-ssrf-guard — SSRF guard for all outbound fetches
- **Phase:** SEC   **Status:** ENG   **Tags:** (B)

## Scope
Build a single, reusable outbound-fetch guard and route **every** crawler/tool HTTP fetch through it
(currently only `backend/app/agents/web_searcher.py` does raw `httpx` fetches with
`follow_redirects=True` and zero validation — the highest-severity code gap called out in the design).

Requirements (design §7.2 "SSRF guard (crawler)"):
- **Scheme allow-list**: `http`/`https` only — reject everything else (`file://`, `ftp://`, `gopher://`, etc.).
- **Resolved-IP validation**: resolve the hostname and reject if the resolved IP is private
  (RFC1918), loopback, link-local (incl. the cloud-metadata address `169.254.169.254`), or otherwise
  non-public (multicast, reserved). Validate the IP **actually connected to**, not just the literal
  hostname string (guard DNS-rebinding: don't trust a hostname that resolved to a public IP on a first
  check but a private IP on the real connect — either resolve once and connect to the resolved IP
  directly, or use an httpx transport hook that validates the socket's peer address).
- **Bounded redirects, re-validated per hop**: cap redirect count (e.g. 3-5); do **not** use
  `follow_redirects=True` blindly — each hop's target URL must pass the same scheme + IP checks before
  being followed.
- **Host allow/deny list**: structure so a deny-list (at minimum: localhost, `*.internal`, the compose
  service names `db`, `redis`, `backend`) is enforced, with room for a future allow-list of trusted
  domains (Coursera/Udemy/edX/etc. for P6) — don't over-build P6-only allow-list logic now, just leave
  the seam.
- **Timeouts + response-size caps**: connect/read timeouts and a max-bytes cap enforced while streaming
  (abort mid-download if exceeded), not just via `Content-Length` header (which can lie).

Implementation:
- New module, e.g. `backend/app/guardrails/ssrf_guard.py` (or `backend/app/net/ssrf_guard.py` — engineer's
  call, but it must live in a shared location importable by any current/future crawler or tool, not
  duplicated). Expose a small interface, e.g. an async `safe_fetch(url, ...) -> Response` or an httpx
  transport/client factory `build_guarded_client()`, whichever fits `web_searcher.py`'s existing usage
  best with minimal churn.
- Replace the raw `httpx` fetch in `backend/app/agents/web_searcher.py` (~line 270,
  `client.stream("GET", url, follow_redirects=True, ...)`) to go through the guard.
- Grep the backend for any other outbound `httpx`/`requests`/`aiohttp` calls that fetch **externally
  supplied URLs** (crawler, tool results, anything driven by an LLM tool-call argument or by content
  extracted from a document/page) and route those through the guard too. Calls to our own fixed,
  hardcoded internal service URLs (e.g. talking to Postgres/Redis/HF inference endpoints via their own
  SDKs) are out of scope — this guard is specifically for fetching **externally-supplied/attacker
  -influenceable URLs**.

## Acceptance criteria
- [ ] Guard rejects non-http(s) schemes.
- [ ] Guard rejects a URL that resolves to a private/loopback/link-local IP, including
      `169.254.169.254`.
- [ ] Guard rejects a redirect chain that points to a private IP on hop 2+ even if hop 1 was public
      (redirect target re-validated, not just the original URL).
- [ ] Guard enforces a max redirect count.
- [ ] Guard enforces a response-size cap (streamed enforcement, not just header trust).
- [ ] `web_searcher.py` no longer calls raw `httpx` with `follow_redirects=True` unguarded — it goes
      through the new guard.
- [ ] Unit tests cover: scheme rejection, private-IP rejection (mock DNS resolution), redirect
      re-validation, size-cap enforcement, and a happy-path public URL fetch.

## Design references
- dev-board/app-design-and-features.md §7.2 "SSRF guard (crawler)" and the SSRF row in §10 Risks table.
- dev-board/tasks.md — SEC block, item **S1**.

## Constraints / non-goals
- Do not build the P6 course-provider allow-list logic yet — just leave an extensible interface.
- Do not touch `docker-compose.yml` port publishing here — that is SEC-03/S5, a separate task.
- Keep it dependency-light: prefer stdlib `socket`/`ipaddress` + `httpx` transport hooks over adding a
  new heavyweight library.
