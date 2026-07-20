# Sentry error tracking (free tier)

Sentry is the app's **unhandled-exception alerting channel** (§6.24 / §7.7) — a free-tier
"something threw in production" notifier. It is deliberately **not** an APM / distributed-tracing
tool (that is OpenTelemetry's job, §7.8) and **not** an on-call / incident-response programme.

Everything is **off by default**: with no `SENTRY_DSN` set, Sentry is a complete no-op (no SDK
calls, no network), so local dev, CI and tests need no account. PII scrubbing is always on when
enabled.

## Enable it (once, per deploy)

1. Create a free Sentry account and a **project** (platform: Python / FastAPI). Copy the project
   **DSN**.
2. Set it as a secret on the deploy (HF Space Secrets / env) — never commit it:

   | Variable | Value | Notes |
   |----------|-------|-------|
   | `SENTRY_DSN` | `https://…@…ingest.sentry.io/…` | Enables Sentry. Empty = no-op. |
   | `SENTRY_ENVIRONMENT` | `production` / `staging` | Optional; filters issues per deploy. |
   | `SENTRY_TRACES_SAMPLE_RATE` | `0` (default) | Leave at 0 — tracing is OTel's job, don't double-pay. |

   The same init runs in both the web process (FastAPI app factory) and each Celery worker
   (post-fork), so both API and background-task exceptions are reported.

## PII scrubbing (always on when enabled)

The app enforces scrubbing in code — you do **not** rely on Sentry-side data-scrubbing settings
(though you can leave Sentry's "Data Scrubber" defaults on as a belt-and-braces second layer):

- `send_default_pii=False` — the SDK never attaches the client IP, cookies, or request body.
- `include_local_variables=False` — stack-frame local variables (which routinely hold chat/CV
  free text like `messages` / `content` / CV strings the contact-only redactor can't recognise)
  are never attached to captured exceptions.
- `max_request_body_size="never"` — belt-and-braces: the request body is never captured at all.
- A `before_send` / `before_send_transaction` hook (`app/observability/sentry.py`) additionally:
  - **drops** the request **body**, **query string** and **cookies** (where chat message / CV
    text and OAuth codes would leak), and strips `Authorization` / `Cookie` / API-key / auth /
    CSRF headers;
  - **drops** user-identifying fields (`email` / `username` / `ip_address` / `name`) — only an
    opaque `id` may remain;
  - **redacts** residual contact PII (email / phone / URL / postal address / name) from every
    remaining string in the event, reusing the same deterministic redactor used at the LLM
    egress boundary;
  - **fails closed** — if scrubbing raises, the event is dropped rather than sent un-scrubbed.

Net effect: Sentry events never contain chat message content, CV text, or contact-detail PII.

## Low-noise alert rule (set this in the Sentry dashboard)

Sentry's out-of-the-box alert is **"email on every new issue"**, which floods a free-tier inbox.
This is dashboard config (not app-enforceable), so configure it once per project:

1. **Settings → Alerts → (delete/disable the default "new issue" rule)**, then create an
   **Issue Alert** with a low-noise condition, e.g.:
   - **When:** *An issue is seen more than* **`5`** *times in* **`1 hour`** — (so a one-off
     transient blip does not page you), **and**
   - **If:** the issue's `level` **equals** `error`/`fatal` and `mechanism` is **unhandled**
     (only real unhandled exceptions, not handled/logged warnings), **and**
   - **Then:** send a notification to your email (or a single Slack channel).
2. Set the **rule action interval** to at least **60 minutes** so a noisy issue notifies at most
   once an hour.
3. Optionally enable the **weekly digest** and disable per-event emails for everything else.

Tune the threshold to your traffic; the goal is "tell me about recurring, unhandled failures",
not "email me on every exception".

## Verify delivery (after a real DSN is set)

An **admin-only** endpoint raises a deliberate unhandled error:

```
GET /api/_debug/sentry-test        # requires an is_admin session (see docs/admin-access.md)
```

With `SENTRY_DSN` set, the resulting `500` appears as an issue (`SentryTestError`, PII-scrubbed)
in the project within a minute. With no DSN it is just a normal `500`. This is verification
tooling only — it is not part of any product flow, and a non-admin caller gets `401`/`403`.
