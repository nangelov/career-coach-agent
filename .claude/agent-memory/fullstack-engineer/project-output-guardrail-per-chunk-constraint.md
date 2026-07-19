---
name: project-output-guardrail-per-chunk-constraint
description: screen_output runs per token-delta on the streaming path — keep ML opt-in (default None), only the buffered node gets a classifier
metadata:
  type: project
---

`screen_output` (P10-03, `app/guardrails/heuristics.py`) is invoked **per token delta** on the
live streaming path (`ChatService._stream_response`), and once over the whole answer on the
buffered path (`agents.graph.output_guardrail_node`).

**Why:** an ML classifier call per streamed delta is prohibitively slow. So any expensive
detector added to `screen_output` must be an **opt-in keyword seam** (`classifier=None` default,
regex-only) — only the buffered full-answer node passes the classifier
(`default_injection_classifier()`); the streaming path stays deterministic regex-only. The
buffered path can't retract already-emitted tokens anyway, so re-screening the accumulated
stream is pointless for user-facing redaction.

**How to apply:** when adding output-side detection, keep the deterministic regex nets on both
paths and gate ML/latency behind the opt-in arg. Leakage/injection *signatures* stay
self-contained regexes in heuristics (like `_DENY_PATTERNS`) — do NOT import
`RESPONDER_SYSTEM_PROMPT`/responder into guardrails (closes the [[project-guardrails-agents-cycle]]).
