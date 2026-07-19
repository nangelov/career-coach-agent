# Task P10-02-abuse-offtopic-pii-scrub — abuse filter completed + PII scrub before tools/external calls

- **Phase:** P10   **Status:** ENG   **Tags:** (B)

## Scope
Two related pieces of the input-guardrail layer (design §7 / §7.4 / §7.6):

1. **Abuse / off-topic filter completed.** Topic scoping already exists via the planner's intent
   classification (`OFF_TOPIC` → refuse, `JOB_HUNTING` → redirect — P4/P6, design §7.4). Audit that
   path end-to-end: confirm both outcomes are reachable, tested, and use the right response shape
   (refusal vs. redirect are *not* the same thing — a redirect must still answer with market
   requirements and steer back to development, not just refuse). Close any gap you find (e.g.
   missing redirect copy, missing test coverage, a path that falls through to a generic answer
   instead of refusing/redirecting). This is a completion pass, not a rewrite — don't touch the
   planner's classification mechanism unless it's actually broken.
2. **PII scrub before content hits tools or external APIs** (design §7 bullet: "PII scrubbing before
   content hits tools or external APIs"). Note this is **distinct** from SEC-08's contact-detail
   redaction at the **LLM egress boundary** (§6.16 — name/email/phone/address/links/photo stripped
   before CV text reaches the LLM provider) — that's already done (`SEC-08-contact-redaction`).
   This task's gap is upstream: when the agent graph passes user-typed or profile-derived content
   *into a tool call* (e.g. `internet_search`, market-intel crawl queries, dashboard tool inputs),
   confirm nothing PII-dense (raw CV text, contact details) is being forwarded to those tools/external
   APIs (Tavily, etc.) unscrubbed. Read the existing egress redaction module (used by SEC-08) — reuse
   it at the tool-call boundary rather than building a second scrubber (DRY).

## Acceptance criteria
- [ ] Off-topic requests are refused with `REFUSAL_MESSAGE` (or equivalent); job-hunting requests
      are redirected to a market-requirements answer + steer-back copy — both paths covered by tests.
- [ ] Content passed into tool calls (search queries, crawl targets, dashboard tool payloads) is
      confirmed free of raw contact-PII before it leaves the process boundary; add a guard/scrub call
      at the tool-invocation seam if a gap is found, reusing the SEC-08 redaction primitive.
- [ ] New/updated tests demonstrate: an off-topic message is refused; a job-hunting message is
      redirected (not refused); a tool-call input containing an email/phone is scrubbed before
      dispatch.
- [ ] `ruff`, `ruff format --check`, `mypy`, `pytest` all green.

## Design references
- dev-board/app-design-and-features.md §7 (input guardrails bullet), §7.4 (topic scoping), §7.6
  (contact-detail redaction, §6.16)
- dev-board/code-review/SEC-08-contact-redaction/ — the egress redaction primitive to reuse
- dev-board/code-review/P6-04-market-agent-and-guardrail/ — where the S3 topic guardrail landed

## Constraints / non-goals
- Do not rebuild the topic guardrail's classification logic (P4/P6 territory) — only close gaps
  in its completeness/reachability.
- Do not duplicate SEC-08's redaction logic; extend/reuse it.
