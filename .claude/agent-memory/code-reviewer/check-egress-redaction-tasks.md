---
name: check-egress-redaction-tasks
description: Reviewing SEC PII-redaction-at-LLM-egress tasks (llm/redaction.py wired into LLMRouter) — chokepoint proof, blanket-scope side effects, best-effort false positives
metadata:
  type: project
---

Reviewing SEC-08-style "redact contact PII before external inference" tasks (utility in `backend/app/llm/redaction.py`, wired into `LLMRouter.complete`/`.stream`).

**Why:** design §6.16/§7.6 requires stripping directly-identifying CV fields (name/email/phone/address/personal-URL) at ONE `llm/` chokepoint before the third-party provider call, keeping employers/titles/dates/skills/education. Budget = regex/heuristic, not NER (same posture as `guardrails/heuristics.py`).

**How to apply — check on every such task:**
- **Chokepoint proof, not unit-in-isolation.** The router-integration test must assert on the messages a fake/recording `LLMClient` *actually received* (redaction happened before `client.complete`/`.stream`), not just call the utility. `redact_messages` must be at the top of BOTH `complete` and `stream` before the client loop.
- **No duplication.** Grep `backend/app` for `redact`; must be only the utility + router wiring + exports. Nothing in `structuring.py`/`responder.py`/`planner.py`/`tools/`.
- **Blanket-scope side effects (the real reviewer value-add).** Redacting ALL outbound content (all roles) also hits `role="tool"` messages — web-search / job-search results flowing back to the responder. Blanket URL redaction strips job-posting/source links so the coach can't surface them. This is the task's *sanctioned default* but "visibly breaks a chat flow" — flag as a follow-up/architect question, do NOT gate (task explicitly allowed it).
- **False positives are documented best-effort, not blockers.** Verified real ones: first-line "Firstname Lastname" heuristic redacts benign 2-3-word openers ("Thank You"); `<n> <Word> <street-suffix>` over-matches ("5 Sales Drive"); two-separator digit grouping ("100 000 5000") → phone. All fail-safe (over-redact = correct direction at egress). Confirm the conservative phone regex leaves CV date ranges (`2019-2023`) intact.
- CV substance preservation and a limitations docstring (matching guardrails honesty convention) are acceptance criteria — verify both. Embeddings pipeline is out of scope (stored vectors, separate task).
- Running tests needs `HF_API_TOKEN=x DATABASE_URL=postgresql://x JWT_SECRET_KEY=x` env + the backend `.venv` (`python` isn't on PATH; use `backend/.venv/bin/python`).
