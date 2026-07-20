# Code review — P11-01-otel-tracing · engineer revision 1

## Verdict: CHANGES_REQUESTED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major | backend/app/observability/redaction.py:74-91, 51-65 | The redaction module is the **only** line of defense for FastAPI auto-instrumentation spans (the "primary guarantee that instrumentation sets only-safe-attrs" applies to app-owned spans, not to auto-instrumentation). But `redact_contact_details` only neutralises contact PII, and its URL regex requires a `https?://`/`www.` scheme. ASGI/FastAPI instrumentation sets `http.target` (and/or `url.query`) as a **scheme-less** `path?query` string, so an OAuth callback like `/api/auth/callback?code=<authcode>&state=<token>` is neither dropped (those key names aren't in `_SENSITIVE_KEY_SUBSTRINGS`) nor scrubbed (no scheme → URL regex misses it). Result: OAuth authorization codes / `state` / any `?token=` query secret is exported to the third-party OTLP backend when `OTEL_ENABLED`. The module docstring (lines 16-21) explicitly overclaims that "a URL query param captured by HTTP auto-instrumentation is neutralised." | Close the query-string leak: add `target` / `query` / `url.full` / `http.url` (or the specific query-bearing keys) to the drop-or-scrub set, OR disable query capture in the FastAPI instrumentor, OR strip the query portion before export. Then correct/soften the docstring claim. |
| C2 | minor | backend/app/observability/tracing.py:194-198 | `_set_node_start_attributes` stamps `worker.name = <node>` on **every** node (input_guardrail, memory_recall, planner, responder, output_guardrail, memory_writer), not just worker nodes — a misleading attribute on non-worker spans (`graph.node` already carries the identity). | Only set `worker.name` for actual `WorkerName` nodes (or drop it and keep `graph.node`). |
| C3 | nit | dev-board/code-review/P11-01-otel-tracing/engineer.md:64 | Report says "12 tests"; the suite has 11 test functions (`pytest` → 11 passed). | Correct the count. |

## Notes
- Verified locally: `tests/test_observability_tracing.py` → **11 passed**; `scripts/check_curated_deps.py` → OK.
- What holds up well and should not be re-litigated:
  - Redaction is a genuine chokepoint — `build_tracer_provider` wraps the exporter in `RedactingSpanExporter` for **both** the simple and batch processors, and the InMemory test proves scrub-before-delegate. Fails **closed** (drops the batch, returns FAILURE) on a redaction exception.
  - `traced_node` is a transparent sync/async-preserving seam applied via a single `_add` helper in `build_graph`, so new workers auto-get a child span (task requirement met); streaming path (`graph.stream`/`graph.plan`/`graph.responder_stream`) is also spanned.
  - Reuses `app.llm.redaction.redact_contact_details` rather than re-implementing PII detection (per §7.6) — no redaction duplication introduced.
  - Curated-dep posture correct: `opentelemetry-api`/`-sdk` (module-scope) curated into CI + Makefile; the instrumentation packages + OTLP exporter are lazily imported and correctly allowlisted in `check_curated_deps.py`. Default-off + fail-soft throughout; opt-in `docker-compose.otel.yml` layers on top without changing default `docker compose up` (service names backend/worker/beat all match).
- Out of scope / correctly deferred: the full HTTP→node→Celery single-trace assertion is left to P11-05-verify (acceptable — needs the live Collector).
- Non-gating observation: wrapping async-generator `yield`s inside a `with span` (`graph.stream`, `trace_async_iter`) is timing-only and functionally fine, but under real ASGI can attach/detach OTel context across suspension points; acceptable for latency spans, worth a glance in P11-05.

---

# Code review — P11-01-otel-tracing · engineer revision 2

## Verdict: APPROVED

## Re-verification (revision 1 findings C1/C2/C3)
| id | prior severity | status | evidence |
|----|----------------|--------|----------|
| C1 | major | **Resolved** | `redaction.py`: `"query"` added to `_SENSITIVE_KEY_SUBSTRINGS` (drops bare query attrs — `url.query` / `http.request.query_string` — wholesale) AND a new `_URL_KEY_SUBSTRINGS` (`http.target`/`http.url`/`url.full`/`url.path`) + `_strip_query_string` strips the `?query`/`#fragment` tail off request-URL keys. A scheme-less OAuth callback `/api/auth/callback?code=…&state=…` now exports as just `/api/auth/callback` — the leak the value-level redactor missed is closed at the key layer. Module + `_redact_value` docstrings corrected (no longer overclaim the value redactor covers scheme-less query params). New tests `test_redact_attributes_strips_scheme_less_query_secrets` + `test_redact_attributes_drops_bare_query_attribute` both cover it. |
| C2 | minor | **Resolved** | `tracing.py:_set_node_start_attributes` gained an `is_worker` flag; `worker.name` is stamped only when true. `graph.py`'s `_add` passes `is_worker=True` for exactly the five `WorkerName` fan-out nodes; guardrail/recall/planner/responder/memory-writer carry only `graph.node`. Test `test_worker_span_stamps_worker_name_but_planner_does_not` + planner-span assertion confirm. |
| C3 | nit | **Resolved** | Suite now has 14 test functions; report figures updated (963 total / 14 in file). |

## Notes
- Verified locally: `tests/test_observability_tracing.py` → **14 passed**.
- C1 fix ordering is correct: `_is_sensitive_key` drop (`continue`) runs before the URL-key strip, so `url.query` is dropped, not merely trimmed; schemed URLs (`url.full`) are value-redacted then query-stripped. No residual query-bearing FastAPI attribute left uncovered.
- All revision-1 "holds up well" items unchanged (chokepoint wraps both processors, fails closed, transparent `traced_node` seam, curated-dep posture, default-off/fail-soft). HTTP→node→Celery single-trace assertion remains correctly deferred to P11-05-verify.
