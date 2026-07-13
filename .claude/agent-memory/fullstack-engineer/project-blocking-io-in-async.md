---
name: project-blocking-io-in-async
description: Never call blocking stdlib IO (e.g. socket.getaddrinfo) directly from an async method on the SSE/request path; offload + bound it
metadata:
  type: feedback
---

Blocking stdlib calls (DNS `socket.getaddrinfo`, sync file/network IO) must not run directly on
the event loop from an `async` method — reviewers gate this as an event-loop DoS, especially on
the SSE request path where LangGraph nodes run async and one slow call stalls all concurrent
user streams.

**Why:** an attacker-influenced host can point at a DNS server that hangs; with no offload the
whole loop blocks. Code-reviewer flagged this as a major finding on SEC-01.

**How to apply:** offload to a worker thread and bound it —
`with anyio.fail_after(timeout): await anyio.to_thread.run_sync(fn, *args, abandon_on_cancel=True)`.
`abandon_on_cancel=True` is REQUIRED for the timeout to actually free the loop — the default
(False) makes `fail_after` wait for the thread to finish, so a hang test won't pass and the loop
isn't freed. anyio is already a direct dep. Keep a sync entrypoint too (for sync/test callers) by
splitting cheap non-blocking checks into a shared helper reused by both sync and async variants
(DRY). Map timeout/OSError to the domain error type. See [[project-composition-root]].
