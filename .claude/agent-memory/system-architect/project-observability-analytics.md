---
name: project-observability-analytics
description: LOCKED §6.26-27/§7.8 — OpenTelemetry+free OTLP backend+Sentry for telemetry, GA4 for engagement; admin access via provider login not a new password surface; new P11 phase, old P11 shifted to P12
metadata:
  type: project
---

Owner-decided 2026-07-13; written into design §6.26–§6.27 / §7.8, plan.md (new Phase 11 + renumbered Phase 12),
tasks.md (new P11 section + renumbered P12). Gate on these.

- **§6.26 Observability = OpenTelemetry (vendor-neutral SDK)**, instrumenting FastAPI + the LangGraph node graph
  (planner/workers/responder spans) + Celery tasks, exported via **OTLP to a free-tier hosted backend** (owner's
  choice — Grafana Cloud free / Honeycomb free / similar). **PII-redacted, retention-limited at the source** —
  this is the same obligation as the pre-existing §7.6 "traces would otherwise contain full CV text" warning
  (was task S11), now given a concrete implementation rather than left open. **No bespoke in-app telemetry
  dashboard** — reject any PR that builds one; the OTLP backend's own UI is the dashboard (YAGNI).
- **Admin-access ruling (important, reject deviations):** the user floated "admin user/pass" for accessing
  telemetry as an option — **rejected**. Access to the telemetry backend's dashboard is the **chosen provider's
  own login** (e.g. enable Google sign-in on Grafana Cloud/Honeycomb). This app does **not** grow a second,
  password-based admin surface — that would directly violate the locked SSO-only decision (§6.2 /
  [[project-auth-session-seam]]). In-app admin actions (feedback/user-data access) keep using the existing
  `is_admin`-flagged SSO account (P3-05, see [[project-admin-authz]]) — no new endpoint, no new auth path.
- **Sentry (§6.24) is retained separately** as the dedicated error-alerting channel; OTel adds traces/metrics/
  logs for performance + engagement, it does not replace Sentry. Both land in the same new phase (bundled, not
  split across P11/P12) since they're both "day-2 ops" work.
- **§6.27 Product engagement analytics = Google Analytics 4 (`gtag.js`)**, reintroduced from v1's
  `ChatBot.tsx`/`PDPDialog.tsx` pattern (pageviews + button-click events: send-message, stop, upload-cv,
  generate-pdp, submit-feedback, thumbs up/down, dashboard actions). **Event payloads must never carry message
  content, CV text, or other PII** — interaction events only. Loads only after the consent gate (§6.22) is
  accepted — reject any PR that loads `gtag.js` before consent.
- **Phase renumbering:** a new **Phase 11 "Observability, telemetry & product analytics"** was inserted between
  P10 (Guardrails) and the 🛑 pre-go-live review, so that review inspects *real* telemetry instead of a promise
  of it. The old Phase 11 ("Deploy, parity & cutover", including the 🛑 pre-go-live review) is now **Phase 12**.
  S11 (log/trace PII redaction) and S15 (Sentry) moved from the old-P11/[SEC] table into the new P11; S9
  (denial-of-wallet), S10 (contact-detail redaction "before P11"), and S16 (key-rotation runbook) now target
  **P12**. If reviewing any task referencing "P11" written before 2026-07-13, check which phase it now means.

See [[project-privacy-ops-decisions]] for the adjacent §6.16-25 rulings and the 🛑 pre-go-live review ruling
(now under P12). See [[project-security-privacy-posture]] for the [SEC] block.
