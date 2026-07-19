# Engineer report — P10-03-output-guardrails · Revision 1

## Summary
Completed the **output guardrail** (design §7 "block system-prompt leakage … strip injected
instructions echoed from untrusted content" / §7.3 point 4). `screen_output` now runs three
redaction stages over the final answer, keeping the existing `OutputScreenResult`
(`text`/`verdict`/`modified`) contract:

1. **Echoed-injection deny-list** (unchanged P4-08 net) — canonical injection/jailbreak phrasing
   echoed back out of untrusted grounding is redacted.
2. **System-prompt leakage** (new) — distinctive fixed scaffolding from the assistant's own
   instructions / the untrusted-content fence coaxed back into the answer is detected via
   `_LEAKAGE_PATTERNS` (case/whitespace-tolerant → verbatim *and* near-verbatim) and redacted.
3. **Classifier net** (new, opt-in) — the **P10-01** injection classifier scores each
   sentence/line of the answer and redacts flagged segments, so a *non-canonical* echoed
   instruction the deny-list misses is caught — one detection mechanism, not two.

A redaction neutralises rather than blocks (answer still returned, `allowed=True`).

## Files changed
- `app/guardrails/heuristics.py` — added `_SYSTEM_PROMPT_LEAK` category + `_LEAKAGE_PATTERNS`;
  `screen_output(text, *, classifier=None)` combined-regex pass + opt-in classifier segment net
  (`_redact_flagged_segments` / `_has_letter` / `_OUTPUT_SEGMENT_SPLIT`); public
  `default_injection_classifier()` accessor; refreshed module docstring.
- `app/agents/graph.py` — `output_guardrail_node` passes `default_injection_classifier()` (the
  buffered full-answer path can afford a model call); docstring updated.
- `app/guardrails/__init__.py` — export `default_injection_classifier`; refreshed header comment.
- `app/guardrails/untrusted_content.py` — refreshed the stale "P10 replaces the coarse nets" note.
- `tests/test_output_guardrails.py` (new) — 10 tests (leakage verbatim/near-verbatim/fence,
  clean pass-through with & without classifier, canonical echo strip, classifier segment redact,
  fail-soft, combined nets, buffered-node wiring).

## Key decisions
- **Leakage signatures are self-contained regexes** (like `_DENY_PATTERNS`), not imported from
  the responder/fence. `guardrails` is a *lower* layer than `agents` — importing
  `RESPONDER_SYSTEM_PROMPT` would close an import cycle (documented in the module). Comment flags
  the coupling to keep in sync; the fence markers are label-agnostic so they survive a rename.
  Signatures are long/specific to avoid snagging ordinary prose (default-open posture).
- **Classifier is opt-in (`classifier=None` default), not auto-defaulted.** The per-chunk
  streaming path (`ChatService._stream_response`) calls `screen_output(chunk.content)` per token
  delta — a per-delta model call would be prohibitively slow. So only the **buffered**
  `output_guardrail_node` (sees the whole answer) passes the classifier; streaming stays
  deterministic regex-only (deny-list + leakage nets still run there). Mirrors `screen_input`'s
  optional-classifier seam and honors "don't re-plumb the wiring" (task constraint).
- **Reuse P10-01, don't duplicate detection.** `_redact_flagged_segments` calls the same
  `InjectionClassifier.classify` the input gate uses; the shared singleton is exposed via
  `default_injection_classifier()`. Fail-soft: an unavailable classifier (`classify` → `None`)
  redacts nothing (default-open, mirroring `screen_input`'s fail-open).
- **Segment-level redaction** (sentence/line split, delimiters preserved) so a flagged clause is
  surgically removed and clean text is returned byte-for-byte when nothing is flagged.

## How to verify
```
cd backend && . .venv/bin/activate
ruff check app/guardrails app/agents/graph.py tests/test_output_guardrails.py
ruff format --check app/guardrails app/agents/graph.py tests/test_output_guardrails.py
mypy app/ migrations/
python scripts/check_curated_deps.py
python -m pytest tests/test_output_guardrails.py tests/test_untrusted_content.py -q
python -m pytest -q
```

## Tests (final step — mandatory)
- `ruff check` (all changed files) → All checks passed. `ruff format` → clean (heuristics.py
  reflowed by the formatter, re-checked clean).
- `mypy app/ migrations/` → Success: no issues found in 159 source files.
- `python scripts/check_curated_deps.py` → Curated-dependency guard OK (no new dep — reuses the
  P10-01 classifier + in-tree regex).
- `python -m pytest -q` (full suite) → **899 passed, 83 skipped** (+10 new tests over the P10-02
  baseline of 889; skips are the unchanged live-DB/ML set with no Postgres/model locally).
  Existing `test_untrusted_content.py` `screen_output` regression tests pass unmodified.
- No failures; no test weakened or deleted. In the local venv `transformers` is absent, so
  `default_injection_classifier()` fails soft (→ `None`) — the buffered-node test still redacts
  via the regex leakage net, and the classifier-specific tests inject a deterministic fake.

## Self-check
- [x] Meets acceptance criteria: verbatim/near-verbatim system-prompt leakage redacted; echoed
  injection still caught (regression green) and now also benefits from the P10-01 classifier
  (opt-in) rather than a second mechanism; new tests cover leak-redact / clean-pass-unmodified /
  fenced-echo-strip; ruff/format/mypy/pytest green.
- [x] No secrets; guardrails layering respected (interface reused, no agents import at module
  top — cycle avoided); wiring not re-plumbed beyond the one buffered-node classifier arg.
- [x] Tests/lints pass (pasted above).
