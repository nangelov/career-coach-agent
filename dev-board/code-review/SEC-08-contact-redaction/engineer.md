# Engineer report — SEC-08-contact-redaction · Revision 1

## Summary
Added contact-detail redaction at the single LLM egress chokepoint (design §6.16 / §7.6).
A new pure, deterministic utility strips directly-identifying PII (name, email, phone,
postal address, personal URLs) from outbound message content, while preserving the CV
substance the coach reasons about (employers, titles, dates, skills, education). It is
wired into `LLMRouter.complete` and `LLMRouter.stream` so redaction happens **once**,
before any underlying `client` call, regardless of caller — no redaction logic is
scattered into `structuring.py` / `responder.py` / `planner.py`.

## Files changed
- `backend/app/llm/redaction.py` (new) — `redact_contact_details(text)` +
  `redact_messages(messages)`; compiled regex/heuristic patterns per category, with a
  module docstring documenting each category's best-effort coverage limits (honest-
  limitations convention, mirroring `guardrails/heuristics.py`).
- `backend/app/llm/router.py` — call `redact_messages(...)` at the top of `complete`
  and `stream` (the confirmed only production path to a real model call).
- `backend/app/llm/__init__.py` — export the two new functions.
- `backend/tests/test_llm_redaction.py` (new) — utility + router-integration tests.

## Key decisions
- **Blanket redaction of all outbound message content at the router** (all roles), per
  the task's "one place, not scattered" instruction. This naturally covers both the
  CV-structuring input and the RAG-grounding path (retrieved own-CV `kb_chunks`) without
  per-agent tagging. Only `content` is touched; message metadata and model-generated
  `tool_calls` args are left intact (out of scope for this boundary).
- **Conservative phone regex** (two-separator US grouping or a `+`-prefixed intl number)
  so a same-shaped date range like `2019-2023` is not mis-redacted — protecting CV dates.
- **Name is heuristic**: an explicit `Name:` line anywhere, plus a bare "Firstname
  Lastname" line only when it is the first non-empty line (résumé-header pattern).
  Documented as best-effort / not guaranteed.
- **Address is best-effort/partial** (`<number> <street> <suffix>` and `City, ST 00000`);
  ZIP is anchored to a `City, ST` prefix to avoid mangling 5-digit numbers (e.g. salaries).
- **Photo/image redaction: N/A** — no current path sends raw image bytes to the chat LLM
  (P5 VLM-OCR is only reserved). Noted in the module docstring as an accepted current-
  state limitation, not a gap.
- Mid-stream resume `accumulated` prefill is model-generated continuation (from already-
  redacted input) and is intentionally not re-redacted.
- Cheap by design: module-level compiled regexes, no network/ML, unchanged messages
  returned by identity to avoid needless copies on the hot chat path.

## Follow-up (noted, not in scope)
- The embedding pipeline (`llm/embeddings.py`) is deliberately untouched (stored vectors,
  not the external-inference egress path). If stored own-CV vectors should also be
  contact-detail-free, that is a separate task.

## How to verify
```
cd backend && python -m pytest tests/test_llm_redaction.py tests/test_llm_router.py -q
ruff check app/llm/ tests/test_llm_redaction.py
mypy app/llm/redaction.py app/llm/router.py
```

## Tests (final step — mandatory)
- `pytest tests/test_llm_redaction.py tests/test_llm_router.py -q` → **24 passed**.
- Full backend suite `pytest -q` → **491 passed, 54 skipped** (skips are the usual
  ML/live-DB gated tests; no regressions).
- `ruff check` → All checks passed. `mypy app/llm/redaction.py app/llm/router.py` →
  Success, no issues.
- No failures to root-cause.

## Self-check
- [x] Single redaction utility in `backend/app/llm/` covers email, phone, personal URLs,
      best-effort address, best-effort name.
- [x] `LLMRouter` applies it on both `complete` and `stream` before any client call —
      asserted on what the recording client actually receives.
- [x] Employers/titles/dates/skills/education not mangled (explicit preservation test).
- [x] No redaction logic duplicated into structuring/responder/planner — router only.
- [x] Limitations (best-effort address/name, no photo) documented in the module docstring.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (utility lives in
      the `llm/` layer, applied at the router chokepoint).
- [x] Tests/lints/types pass (pasted above).
