---
name: feedback-worker-enum-fanin-tests
description: Adding a WorkerName/Intent enum member breaks graph tests that assert against the full enum set
metadata:
  type: feedback
---

Adding a new `WorkerName` (or `Intent`) member silently breaks tests that assert against the
**whole enum** rather than the dispatched set.

**Why:** `WORKER_NODES` / fan-in edges derive from `WorkerName`, and some graph tests use
`{w.value for w in WorkerName}` (or `set(WorkerName)`) as shorthand for "all dispatched
workers" / "one citation per worker". When the enum grows, those assertions go stale even
though the new worker is correct. Hit on P8-03 adding `WorkerName.DASHBOARD`
(`test_parallel_workers_fan_in_without_clobbering`).

**How to apply:** after adding a worker/intent, grep tests for `for w in WorkerName` /
`set(WorkerName)` / `for i in Intent`. Fix at root: dispatch the new worker in the fan-in test
too, and remember workers that emit **no citation** (like DASHBOARD) must be excluded from
citation-count/citation-worker assertions (`set(WorkerName) - {DASHBOARD}`), not from the
`worker_results`-keys assertion.
