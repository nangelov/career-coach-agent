---
name: project-worker-data-to-responder
description: Request-path workers must put fetched/read data into WorkerResult.content — the responder grounds ONLY on .content, never .data
metadata:
  type: project
---

The Responder builds its grounding block from worker outputs via `_worker_texts`
(`app/agents/responder.py`), which reads **only** `WorkerResult.content` (a string) —
it never consumes `WorkerResult.data`. So any data a worker fetches for an
informational/"read" turn is invisible to the user-facing answer unless it is folded
into `.content`.

**Why:** caught in P8-03 (dashboard worker). Its `read_dashboard` tool returned the full
DashboardSummary inside the tool-calling loop, but `_summarize` discarded the payload and
put only "Read the user's current dashboard." into `.content` (data went to `.data`, which
the responder ignores). Result: "what's on my dashboard?" gets a non-answer even though the
read succeeded. Also common: capturing tool results but dropping the model's final wrap-up
`result.content` from a bounded tool-loop.

**How to apply:** for any new request-path worker (make_*_node) that reads data to answer a
question, verify the read result reaches `WorkerResult.content` (rendered digest or the
model's final wrap-up text), not just `.data`. Watch for tests that assert only
`result.data[...]` — they pass while the read path is hollow end-to-end. Ask for a test that
proves the read content reaches the responder answer.
