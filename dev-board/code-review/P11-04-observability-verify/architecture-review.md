# Architecture review — P11-04-observability-verify · engineer revision 1

## Verdict: APPROVED

Scope check: this is P11's `(T)` exit gate. The right question for a (T) task is *does the verification
demonstrate the design's exit bar with real run evidence, or does it just restate P11-01/02/03's unit
tests?* It demonstrates the bar. All load-bearing claims were spot-checked against the tree and hold.

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | End-to-end trace of a full chat turn (§6.26, §7.8) | One trace spanning HTTP request → planner → ≥1 worker → responder under one root | Real docker-compose OTel run: root `POST /api/chat` + `graph.plan`, `graph.node.planner`, `graph.node.market_intel` (worker), `graph.node.responder`, `graph.responder_stream`, guardrail/memory nodes — node names match the real `app/agents/graph.py` constants (PLANNER/RESPONDER/MEMORY_RECALL/INPUT_GUARDRAIL/OUTPUT_GUARDRAIL/MEMORY_WRITER; `graph.plan`/`graph.responder_stream`) | none |
| A2 | Async work traced (§7.8: Celery instrumented) | Producer + consumer spans across services | `apply_async/tasks.mine_role` + `apply_async/tasks.ping` on `career-coach-backend`, `run/tasks.mine_role` + `run/tasks.ping` on `career-coach-worker` (`celery.state: SUCCESS`) — real enqueue via `GET /api/roles/{role}/requirements` 202 | none |
| A3 | PII-free traces/logs (§7.6 "logs & traces otherwise contain full CV text and every message"; §7.8) | Synthetic PII marker + CV-shaped text meaningfully exercises redaction, zero leakage | Grep of full 6490-line collector dump: 0 matches for name/email/phone/CV markers, 0 email/phone regex hits, 0 bearer/token; `http.url` shows `[URL REDACTED]` (68×); span attrs are counts/booleans only (`worker.result_count: Int(1)`, no `worker.name` on planner — P11-01 C2 fix holds). Redaction driven through the real `RedactingSpanExporter`, not mocked | none |
| A4 | Sentry wiring + PII scrubbing (§6.24, §7.7) | Inert when DSN unset; attempts delivery when set; no PII to Sentry | Inert-when-unset (client None, no crash) and dummy-DSN attempts-delivery (event enqueued, flush clean) both shown; init options `send_default_pii=False`, `include_local_variables=False`, `max_request_body_size=never` confirmed live; PII-safety correctly *cited* from P11-02 `before_send` tests, not re-derived | none |
| A5 | GA4 loads/fires, no content in payloads (§6.27, §7.8) | Script injected + custom events fire; payloads carry no message/CV content | `Analytics.test.tsx` asserts gated script injection; new `analytics.test.ts` asserts `gtag('event', <name>)` for `send_message`/`upload_cv`/`generate_pdp`; content-safety cited from P11-03 `sanitizeParams`. 8 passed | none |
| A6 | Real-account confirmations gated to owner (§6.26 provider-login admin, §6.27 Measurement ID) | Parts needing real third-party accounts deferred, not faked | Owner runbook covers the 3 credentialed confirmations (OTLP backend, real SENTRY_DSN, real GA Measurement ID). Correct call — these cannot be provisioned in-env and faking them would be the wrong evidence | none |

## Cross-cutting checks
- [x] Fits §8 structure — no product code touched; only `frontend/__tests__/analytics.test.ts` added (test asset, not a layer change).
- [x] Honors locked decisions — SSO-only admin surface preserved (§6.26: telemetry admin = provider's own login, no 2nd password surface); no new stores; observability sits in the blessed `observability/` cross-cutting pkg.
- [x] Interfaces-before-implementations — verification drives the real seams (`RedactingSpanExporter`, real graph nodes, real Celery consumer), not stubs, except the documented LLM-transport swap.
- [x] Budget posture — free/OSS/self-hosted; OTLP backend + Sentry + GA4 all free-tier, deferred to owner.

## Notes
- **LLM-transport stub (A1):** HF Inference egress is DNS-blocked in-sandbox, so only the LLM transport was
  swapped for a local OpenAI-compatible stub (not committed). This does not weaken the observability
  verdict — the redaction exporter, the full graph topology, the real `market_intel` worker (real Postgres
  read), and the responder stream are all real code. Consistent with the "bring up → verify → tear down"
  precedent (P2 verify tasks). Honestly disclosed; accepted.
- **Operational finding** (backend/worker/beat are separate image tags — rebuild together) is a real
  deployment footgun surfaced by the run and belongs in the owner runbook. Non-blocking; good catch for P12
  deploy.
- **Follow-up (owner, not this task):** the three real-account confirmations in the runbook are the only
  remaining gap between "verified locally" and "verified in production" — they require a human with the
  accounts and are correctly out of scope here. P11 exit bar is met at the level this task can reach.
- CI/CD `(T)` correctly left to P11-05.
