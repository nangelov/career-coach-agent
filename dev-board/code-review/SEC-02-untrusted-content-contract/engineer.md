# Engineer report — SEC-02-untrusted-content-contract · Revision 1

## Summary
Made the §7.3 "untrusted content = data, never instructions" contract a single shared,
structural thing instead of per-agent conventions:
1. **One fencing helper** (`app/guardrails/untrusted_content.py::fence_untrusted`) rendering the
   BEGIN/END-marker + "data, not instructions, ignore embedded directives" shape. The responder
   grounding block and the CV structuring prompt both call it (no duplicated fencing logic).
2. **CV/OCR text is now fenced** as untrusted DATA before the structuring tool-call (previously a
   bare `f"CV to parse:\n\n{content}"`).
3. **Minimal, deterministic output net** (`guardrails/heuristics.py::screen_output`) reusing the
   *same* `_DENY_PATTERNS` deny-list — strips canonical injection phrasings echoed back out of
   untrusted grounding material. Wired into both the buffered graph path
   (`output_guardrail_node`) and the streaming path (`ChatService._stream_response`).
4. **Tool-call audit** (below): no gap — no LLM completion combines untrusted external text with
   live expandable tool schemas.

## Files changed
- `app/guardrails/untrusted_content.py` — NEW: `fence_untrusted(label, blocks, *, origin, sources=None)`, the single structural fence; pure leaf module (stdlib only).
- `app/guardrails/heuristics.py` — add `screen_output` + `OutputScreenResult` (reuses `_DENY_PATTERNS`, one deny-list both directions); module docstring now covers input+output; `agents.state` types imported lazily (see cycle note).
- `app/guardrails/__init__.py` — export `fence_untrusted`, `screen_output`, `OutputScreenResult`.
- `app/agents/responder.py` — `_grounding_block` now calls `fence_untrusted` (behaviour-preserving de-dup).
- `app/ingestion/structuring.py` — `_build_messages` fences the CV Markdown via `fence_untrusted` ("CV CONTENT").
- `app/agents/graph.py` — `output_guardrail_node` runs `screen_output` on the buffered response (strips echoes, writes scrubbed response only when modified); dropped now-unused `SafetyVerdict`/`GuardrailStage` imports.
- `app/services/chat.py` — `_stream_response` scrubs each streamed content delta via `screen_output` before emitting the `TokenEvent`.
- `tests/test_untrusted_content.py` — NEW: fencing helper, CV-injection, crawled-page injection, output-net (unit + node + streamed service).

## Key decisions
- **`screen_output` lives in `heuristics.py`, not a new module** — the deny-list it must reuse is there; putting it beside `screen_input` keeps one deny-list, symmetric input/output (DRY; §7.3 "reuse the same patterns module, don't fork").
- **Scrub neutralises, does not block** — output verdict stays `allowed=True`; the fragment is replaced with a visible `[removed]` marker (auditable, no silent clause-splicing). Matches "strip/replace", coarse/default-open posture, swappable wholesale by P10.
- **Streaming is scrubbed per-chunk** (`ChatService`), since the graph's `output_guardrail_node` only sees the *buffered* response — on the streaming path the real Responder streams outside the pre-graph. Documented limitation: per-chunk catches phrasing within one delta; cross-chunk windowing is P10.
- **`fence_untrusted` takes an `origin` clause** so provenance wording differs per caller (retrieval tools vs. uploaded document) while the security-relevant "data, not instructions / ignore directives" text stays fixed and identical.
- **Import-cycle fix**: `guardrails` is below `agents`; `agents.state` types are now imported lazily inside the screen functions (+ `TYPE_CHECKING` for annotations), because the new `structuring`/`responder` → `guardrails` edges otherwise close a module-load cycle via `agents.__init__` → `graph`.

## Tool-call audit (acceptance item 3)
Grepped every `tools=`/`tool_choice=` completion call site:
- **planner** (`agents/planner.py`) forces `record_plan`, but its messages are system prompt + recalled memory note + history + `user_message` only — **no CV/crawl/posting text** reaches it.
- **responder** (`agents/responder.py`) is the node that *does* see untrusted grounding material — and it is **never given `tools=`** (confirmed; the `LLMResponder` protocol carries them only to match the router surface, unused).
- **structurer** (`ingestion/structuring.py`) forces `record_profile`; its only tool is that fixed schema (cannot expand scope), and the CV text it carries is now fenced.
- `llm/client.py` / `llm/router.py` are transport layers — they pass through whatever `messages`+`tools` the caller paired; they never inject content.
**Conclusion: no gap — no untrusted text is ever paired with a live, expandable tool schema. No code change needed.**

## How to verify
```
cd backend
.venv/bin/python -m pytest tests/test_untrusted_content.py -q
.venv/bin/python -m pytest -q          # full suite
.venv/bin/ruff check app/ && .venv/bin/mypy app/guardrails/ app/agents/graph.py app/ingestion/structuring.py app/services/chat.py
```

## Tests (final step — mandatory)
- `pytest tests/test_untrusted_content.py -q` → **10 passed**.
- Full suite `pytest -q` → **455 passed, 49 skipped** (skips are live-DB/network only).
- `ruff check app/guardrails/ app/agents/responder.py app/agents/graph.py app/ingestion/structuring.py app/services/chat.py tests/test_untrusted_content.py` → All checks passed.
- `mypy` on all 7 changed source files → Success: no issues found.
- One transient failure hit during dev: a module-load import cycle (`guardrails`→`agents`) surfaced by the new `structuring`→`guardrails` edge. Root cause (a lower layer importing the `agents` package at module top) fixed by deferring that import; not a test bug. Re-ran until green.

## Self-check
- [x] Meets acceptance criteria (shared fence used by both; CV text fenced; output net strips echoes + wired into both response paths; audit written; tests for all three)
- [x] No secrets committed; Router→Service→Agent/guardrail layering respected (guardrails stays a lower layer, no `agents`-package dependency at load)
- [x] Tests/lints pass (results pasted above)
