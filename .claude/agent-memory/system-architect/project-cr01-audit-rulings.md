---
name: cr01-audit-rulings
description: CR-01 whole-codebase audit (post-P2) — APPROVED rev 1 and rev 2 (fix pass); A3-A8 closed; blessed bootstrap.py composition root + AppStateKeys; remaining P3 carry-forwards
metadata:
  type: project
---

CR-01 (2026-07-05, post-P2 design-practices audit): rev 1 **APPROVED** with minor follow-ups
A3-A8; rev 2 fix pass verified and **APPROVED** — all of A3-A8 are now **closed** (do not
re-raise them). P0-P2 codebase conforms to §8 structure, layering, ports-and-adapters, and
every locked decision.

**Why:** holistic pass requested by user; sets the baseline so later reviews don't re-litigate.

**Blessed patterns from the rev-2 fix (hold future work to these):**
- **Composition root = `app/bootstrap.py`** — the only module allowed to import across all
  layers; API modules hold only thin `get_*` dependencies + wire plumbing. P3 (auth Redis) and
  P4 (agents router) must extend this *one* wiring path — a second lazy wiring path is a major
  finding.
- **`app/app_state.py` `AppStateKeys` (StrEnum)** — the single contract for `app.state`
  attribute names; a dependency-free leaf module so repositories may import it. New `app.state`
  keys must be added there, never as bare string literals.
- **Shared ORM mixins in `repositories/models/_mixins.py`** (`CreatedAtMixin`) — new table
  groups subclass it, no local copies.
- **`from_settings` ctor-injection is now uniform across every adapter** (A5 closed) — any new
  adapter reading global `settings` inside a method body is a drift finding.
- **`ChatService` in-memory fallback now logs a warning** (A6, warning option chosen over
  required params to spare ~5 test call sites) — accepted; production wiring via bootstrap
  always injects both.
- **`ToolSchema` lives once in SDK-free `llm/types.py`**, re-exported from `llm/client.py` and
  `tools/base.py`; 4096 dim cross-checked by a test (`DIMENSION == EMBEDDING_DIM`), not a
  cross-layer import.

**Carry-forwards still open (check in P3 reviews; escalate if missed):**
- **A10:** P3 MUST remove the client-trusted `ChatRequest.user_id` interim field
  (see [[conversation-persistence]]).
- **Eager-Postgres vs lazy-Redis asymmetry** deliberately retained in rev 2 (no-behaviour-change
  constraint, rationale in bootstrap.py docstring). Once P3 makes Redis a hard startup
  dependency, the lifespan should warm the Redis pool / `build_chat_service` eagerly to unify
  the fail-fast posture.
- C6 (linear `get_message` scan) deferred to P9 by explicit reviewer instruction.
