# Engineer report — P11-04-observability-verify · Revision 1

## Summary
P11 exit-gate **verification** (not new features). Brought up the opt-in OTel stack against real
Docker infra, drove a real chat turn plus a real Celery flow, and captured collector evidence that
(a) a full turn traces end-to-end (HTTP + graph nodes incl. a worker + responder) and (b) a Celery
task span appears (producer **and** worker-side consumer), with **zero PII** in the exported spans.
Demonstrated Sentry inert-when-unset and attempts-delivery-when-configured (dummy DSN) without
crashing, and added the GA4 "fires ≥1 custom event" proxy test. Stack torn down; the pre-existing
`db`/`redis` left as found. One doc-worthy operational finding (worker/beat are separate image tags
and must be rebuilt alongside `backend`).

### Sandbox caveat (documented, not a defect)
Outbound egress from the containers to the **HF Inference** host is DNS-blocked in this environment
(`[Errno -5] No address associated with hostname` on the first real turn → planner fell back to
`chat`/no-worker, responder errored). To exercise the **real** graph path (planner → worker →
responder) I swapped **only the LLM transport** for a local OpenAI-compatible stub (verification-only
override, kept in scratchpad — not committed). Everything else is the real code: real planner tool-call
parsing, the real `market_intel` worker (real Postgres read), the real responder stream, and the real
`RedactingSpanExporter`. This is the same "bring up → verify → tear down" precedent as the P2 verify tasks.

## Files changed
- `frontend/__tests__/analytics.test.ts` — added one focused test asserting `gtag('event', <name>)`
  fires with the correct GA4 event name for 3 required product actions (`send_message`, `upload_cv`,
  `generate_pdp`) — the automatable proxy for "GA4 real-time shows ≥1 custom event". No product code
  touched; all other P11 files in the tree belong to P11-01/02/03 (not this task).

## Evidence — 1) OTel end-to-end (real docker-compose)
**Stack:** `docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml -f docker-compose.otel.yml -f <llmstub override> up -d`
(collector `debug` exporter → its own log). **Turn:** guest session → `POST /api/chat` with synthetic
PII: name `Jordan Testalias`, email `zzqmarker99@example-fake.com`, phone `+1-555-0142-7788`, CV text
`Senior Data Engineer, 8 years building Spark pipelines at Acme Corp`.

SSE result routed a worker and completed cleanly:
```
event: plan  → {"intent":"market_requirements","steps":[...],"workers":["market_intel"]}
event: token → (7 responder tokens)
event: done  → {"finish_reason":"stop", ...}
```

**Spans captured** (`service.name = career-coach-backend`), grouped:
```
  2 POST /api/chat            (root HTTP span)
  4 POST /api/chat http receive
 18 POST /api/chat http send
  1 GET /api/roles/{role}/requirements   (Celery-enqueue trigger)
  2 graph.plan
  2 graph.node.planner
  2 graph.node.input_guardrail
  2 graph.node.memory_recall
  1 graph.node.market_intel   ← WORKER span
  2 graph.node.responder
  2 graph.responder_stream
  2 graph.node.output_guardrail
  2 graph.node.memory_writer
```
Requirement "planner + ≥1 worker + responder under one trace" → satisfied (`planner`, `market_intel`,
`responder`). Node names are the real `app/agents/graph.py` constants.

**Attribute samples prove counts/booleans-only, no content:**
```
graph.node.market_intel  ->  graph.node: Str(market_intel)
                             worker.name: Str(market_intel)
                             worker.result_count: Int(1)
graph.node.planner       ->  graph.node: Str(planner)     (no worker.name — P11-01 C2 fix holds)
POST /api/chat           ->  http.target: Str(/api/chat)
                             http.url: Str([URL REDACTED])   (request-path redaction)
                             http.method: Str(POST)
```

**Celery task spans** (producer on backend + consumer on worker):
```
apply_async/tasks.mine_role   (career-coach-backend — enqueue traced)
apply_async/tasks.ping        (career-coach-backend)
run/tasks.mine_role           (career-coach-worker)
run/tasks.ping                (career-coach-worker)  -> celery.state: Str(SUCCESS)
```
`GET /api/roles/{never-mined}/requirements` returned `202 {"task_id": ...}` and the worker logged
`Task tasks.mine_role[...] received`; a trivial `tasks.ping` round-trip gave a clean fast consumer span.
`service.name` values seen in the collector: `career-coach-backend` (63) **and** `career-coach-worker` (2).

**PII grep — full collector output (6490 lines): ZERO matches for every marker.**
```
[0] zzqmarker99   [0] example-fake.com   [0] Testalias   [0] Jordan   [0] Acme Corp
[0] 555-0142      [0] 5550142            [0] Spark pipelines   [0] 8 years   [0] close the gap
emails (regex): 0    phone +1 (regex): 0    bearer/authorization/token: 0    "[URL REDACTED]": 68
```
Stack torn down afterward (`compose rm -sf backend worker beat otel-collector llmstub`); `db`/`redis`
left running as found.

## Evidence — 2) Sentry forced error
Ran the P11-02 mechanism in the backend container (no live DSN available):
```
DSN UNSET  -> sentry client: None ; capture_exception -> None ; no crash, process alive   (INERT)
DSN DUMMY (https://public@localhost:9999/1):
   client initialised: True
   send_default_pii: False   include_local_variables: False   max_request_body_size: never
   capture_exception -> event_id d6b83603519b46428117ccc901fb740a   (enqueued for delivery)
   flush(2.0s) completed -> no crash (fire-and-forget over HTTP to an unreachable host)
```
This proves the wiring end-to-end short of a receiving account, and confirms the P11-02 PII-safety
init options are live. **"No PII reaches Sentry"** is covered by P11-02's `before_send` scrub tests
(`tests/test_observability_sentry.py`: body/cookies/query/header drop, user-PII drop, contact-PII
redaction, fail-closed) — not re-derived here.

## Evidence — 3) GA4
- **Loads + fires:** `frontend/__tests__/Analytics.test.tsx` asserts the `gtag.js` script tag is
  injected only once a session exists (and never when disabled / pre-login); the new
  `analytics.test.ts` case asserts `gtag('event', <name>)` fires with the correct name for
  `send_message`, `upload_cv`, `generate_pdp`. `npx jest __tests__/analytics.*` → **8 passed**.
- **No content in payloads:** covered by P11-03's `sanitizeParams` test (drops free-text-shaped
  params before they reach `gtag`) — cited, not re-derived.

## P11 go-live checklist for the owner (needs real third-party accounts)
1. **OTel backend** — point `OTEL_EXPORTER_OTLP_ENDPOINT` (+ `OTEL_EXPORTER_OTLP_HEADERS` for the API
   key) at a free-tier Grafana Cloud / Honeycomb project, set `OTEL_ENABLED=true`, drive one chat turn,
   and confirm the trace (HTTP → `graph.node.*` → `run/tasks.*`) appears in that backend's trace explorer.
2. **Sentry** — set a real `SENTRY_DSN`, then as an admin run
   `curl -H "Authorization: Bearer <admin-session-jwt>" https://<host>/api/_debug/sentry-test`
   and confirm the PII-scrubbed `SentryTestError` issue lands in the Sentry project (see `docs/sentry-alerting.md`).
3. **GA4** — set a real `NEXT_PUBLIC_GA_MEASUREMENT_ID`, rebuild the frontend, sign in / start a guest
   session, then in GA4 → Reports → Realtime confirm a pageview plus ≥1 custom event (e.g. `send_message`);
   in DevTools confirm the event params carry no message/CV text.

## Operational note for the owner (found during verification)
`backend`, `worker`, and `beat` are **three separate compose image tags built from the same
`./backend` context**. Rebuilding only `backend` leaves a **stale `worker`/`beat`** (no P11 code / no
`opentelemetry` package → the worker exported nothing until rebuilt). Always
`docker compose build backend worker beat` together (or rebuild all) when backend deps/code change.

## Tests (final step — mandatory)
- `cd frontend && npx jest` → **25 suites / 224 passed** (was 223; +1 new multi-action GA4 test).
- `cd backend && .venv/bin/python -m pytest tests/test_observability_tracing.py tests/test_observability_sentry.py -q`
  → **27 passed** (unchanged; no backend code touched by this task).
- No failures; nothing weakened or deleted.

## Self-check
- [x] Real docker-compose OTel run: HTTP + graph-node (planner/worker/responder) + Celery
      producer&consumer spans captured; **zero PII** across 6490 collector lines; stack torn down.
- [x] Sentry inert-when-unset and attempts-delivery-when-configured both demonstrated; PII-safety cited from P11-02.
- [x] GA4 script-injection + event-firing proxy passes; content-safety cited from P11-03.
- [x] Owner runbook (3 real-account confirmations) written.
- [x] No secrets committed; only change is a frontend test. Left CI/CD `(T)` item to P11-05.
