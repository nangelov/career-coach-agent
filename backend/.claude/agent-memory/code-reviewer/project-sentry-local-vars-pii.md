---
name: project-sentry-local-vars-pii
description: Sentry init must set include_local_variables=False — send_default_pii=False and a before_send contact-redactor do NOT cover stack-frame locals, which leak chat/CV free text
metadata:
  type: project
---

When reviewing Sentry (or any error-tracker) init in this repo, check `include_local_variables`.

**Fact:** `sentry_sdk.init` defaults `include_local_variables=True`, capturing stack-frame local
values for every exception. `send_default_pii=False` does NOT gate this (it only controls request
body / client IP / cookies). The project's `before_send` scrubber reuses
`app.llm.redaction.redact_contact_details`, which only strips *contact* PII (email/phone/URL/address/
name) — it leaves ordinary free text intact. So a captured local like `messages`/`content`/CV text
(e.g. a paragraph of career history) survives redaction and is sent to Sentry.

**Why:** Task P11-02 (§6.24/§7.6) requires "Sentry events must never contain chat message content, CV
text". The contact-redactor chokepoint is the agreed PII tool but is insufficient for bulk message
content in stack locals — a silent leak once a live DSN is configured.

**How to apply:** Require `include_local_variables=False` in `sentry_sdk.init` (+ defense-in-depth
`max_request_body_size="never"`), with a unit test asserting it in the captured init kwargs. The
request-body/query/cookie/header drop in `scrub_event` is correct but a separate vector — don't let it
mask the stack-locals one. Same reasoning applies to any future error-reporter that captures frame
locals. Related: [[project-chat-llm-review-checks]].
