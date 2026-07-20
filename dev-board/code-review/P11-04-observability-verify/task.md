# Task P11-04-observability-verify — P11 exit verification
- **Phase:** P11   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md P11 item 7: verify a full chat turn traces end-to-end in the OTel backend; force an error and confirm
it reaches Sentry; confirm GA4 real-time events; grep exported traces/logs/GA payloads for CV/message content
— none found. This depends on `P11-01-otel-tracing`, `P11-02-sentry-error-tracking`, `P11-03-ga4-analytics`
(all merged) and is the phase's own `(T)` exit gate, so it must produce **real, run evidence**, not just
restate those tasks' unit tests.

**Real infra is available in this environment** (`docker` + `docker-compose` work) — use it:

1. **OTel end-to-end (real, not mocked):** bring up
   `docker compose -f docker-compose.yml -f docker-compose.otel.yml up -d` (the opt-in stack from P11-01, which
   wires `otel-collector` with a `debug` exporter dumping spans to its own log — see
   `docker-compose.otel.yml` / `otel-collector-config.yaml`). Drive one real chat turn through
   `POST /api/chat` (a query that routes through at least one worker, e.g. triggers the RAG or web-search
   node) using a message containing an unmistakable synthetic PII marker (e.g. a fake email/phone and a
   CV-shaped sentence) so redaction is meaningfully exercised, not vacuously passed. Capture the collector's
   logs (`docker compose ... logs otel-collector`) and:
   - assert spans exist for the HTTP request AND for the graph nodes it actually traversed (planner + at
     least one worker + responder, using the real node-name constants from `app/agents/graph.py`);
   - assert a Celery task span appears if the turn (or a follow-up action, e.g. PDP generation or a dashboard
     proposal) enqueues one — pick whichever real flow is simplest to trigger;
   - `grep` the captured log output for the synthetic PII marker and for common message-content shapes —
     confirm **zero** matches.
   - Tear the stack back down (`docker compose ... down`) when done, matching the project's existing
     "bring up → verify → tear down" pattern used in prior phases' live-integration verification tasks (see
     `dev-board/code-review/P2-*verify*` for the precedent).
2. **Sentry forced error:** no live DSN is available to you. Use the debug/test-error mechanism
   `P11-02-sentry-error-tracking` built, run it with `SENTRY_DSN` **unset** to confirm it's inert (no crash),
   then run it with a syntactically-valid dummy DSN (e.g. `https://public@localhost:9999/1`, pointing nowhere
   reachable) to confirm the SDK attempts delivery without raising/crashing the app (Sentry SDKs are
   fire-and-forget over HTTP) — this proves the wiring end-to-end short of an actual receiving account. Cite
   `P11-02-sentry-error-tracking/engineer.md`'s `before_send` PII-redaction test as the evidence for "no
   PII reaches Sentry" (don't re-derive it). Document in your report the exact one-liner the human owner runs
   once they have a real DSN to get a real Sentry-side confirmation.
3. **GA4 real-time:** no live Measurement ID / GA property is available to you. Cite
   `P11-03-ga4-analytics/engineer.md`'s test asserting event payloads carry no message/CV content as the
   evidence for that half of the requirement. For the "loads + fires" half, write (or reuse if it already
   exists) a frontend test asserting the `gtag` script tag is injected and `gtag('event', ...)` is called with
   the right event name for at least 2–3 of the required actions, using a mocked `window.gtag` — this is the
   automatable proxy for "GA4 real-time shows a pageview + ≥1 custom event." Document the exact manual steps
   (env var to set, what to click, what to check in the GA4 real-time report) for the human owner to do the
   real confirmation once they have a Measurement ID.
4. **Write up a short runbook** (in `engineer.md`, not a new file) titled "P11 go-live checklist for the
   owner": the 3 things that need real third-party accounts/credentials before they're *actually* verified —
   (a) point `OTEL_EXPORTER_OTLP_ENDPOINT`/`OTEL_EXPORTER_OTLP_HEADERS` at a real Grafana Cloud/Honeycomb
   free-tier project and confirm a trace appears there, (b) set a real `SENTRY_DSN` and confirm the forced
   error appears in the Sentry project, (c) set a real `NEXT_PUBLIC_GA_MEASUREMENT_ID` and confirm a pageview +
   event in GA4's real-time report. Keep it to a few lines each — this is a checklist, not a tutorial.

## Acceptance criteria
- [ ] Real docker-compose OTel run captured evidence (spans for HTTP + graph nodes + a Celery task; zero PII
      leakage in the captured log) — pasted/summarized in `engineer.md`, stack torn down afterward.
- [ ] Sentry inert-when-unset and attempts-delivery-when-configured both demonstrated; PII-safety evidence
      cited from P11-02.
- [ ] GA4 script-injection + event-firing proxy test passes; content-safety evidence cited from P11-03.
- [ ] Owner runbook written for the 3 real-account confirmations.

## Design references
- dev-board/plan.md: P11 exit criteria
- dev-board/app-design-and-features.md: §6.26, §6.27, §7.6, §7.7
- Precedent for "bring up real infra → verify → tear down" verification tasks:
  `dev-board/code-review/` P2/SEC/P6 `*verify*` folders.

## Constraints / non-goals
- Don't re-implement or duplicate the unit tests already written in P11-01/02/03 — cite them.
- Don't require real paid/free-tier third-party credentials to pass — this task's own acceptance criteria must
  be satisfiable with local/mocked infra; the runbook covers the parts that genuinely need a human with an
  account.
- Leave the P11 CI/CD verification `(T)` item to the next task (`P11-05-cicd-verify`) — don't do it here.
