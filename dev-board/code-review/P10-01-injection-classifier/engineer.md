# Engineer report — P10-01-injection-classifier · Revision 2

## Summary
Replaced the P4 regex deny-list as the *actual* input gate with a real, in-process
jailbreak/prompt-injection classifier (S8, design §7.4). `screen_input` now runs the deny-list
only as a cheap fast-path pre-filter, then defers the real decision to a small HF
`Prompt-Guard`-family model (`meta-llama/Llama-Prompt-Guard-2-86M`) run in-process via
`transformers` — the same no-per-call-cost posture as the in-process embeddings (P2-06), no
paid inference dependency. Contract, graph wiring, and `SafetyVerdict(stage=INPUT)` shape are
unchanged; `screen_output` is untouched (output guardrails are P10-03).

## Files changed
- `app/guardrails/injection_classifier.py` (new) — `InjectionClassifier` ABC + `PromptGuardClassifier`
  adapter (ports+adapters, mirrors `app/llm/embeddings.py`): lazy pipeline load, injectable
  `pipeline_factory` seam, thread-locked single build, fail-soft `None` on unavailable/raising
  model, and `_malicious_score` reducer over the `transformers` output shapes.
- `app/guardrails/heuristics.py` — `screen_input` gains a keyword-only `classifier=None` arg;
  two-stage logic (deny-list pre-filter → classifier gate); lazy default-classifier singleton;
  updated module docstring. Positional `(str) -> SafetyVerdict` contract preserved.
- `app/config.py` — `INJECTION_CLASSIFIER_MODEL` (default `meta-llama/Llama-Prompt-Guard-2-86M`)
  and `INJECTION_CLASSIFIER_THRESHOLD` (default `0.5`, bounded 0–1).
- `pyproject.toml` — added `transformers>=4.40.0` (heavy/lazy ML dep).
- `scripts/check_curated_deps.py` — added `transformers` to `INTENTIONAL_EXCLUSIONS` (excluded
  from the curated CI/dev venv, like `sentence-transformers`).
- `tests/test_injection_classifier.py` (new) — 12 unit tests.

## Key decisions
- **In-process `transformers`, not a paid API** (task/§6/§11 budget). Lazy-loaded on first
  `classify`, never at import/construction, so CI/sandbox trigger no download; the pipeline
  build is behind an injectable `pipeline_factory` seam for deterministic testing — identical
  pattern to the embedding client.
- **Deny-list kept as fast-path pre-filter** (task allows this; it's the cheap net that
  short-circuits obvious canonical phrasings before any model call). The classifier is the
  actual gate for everything the pre-filter misses.
- **Fail *open* on classifier-unavailable.** `classify()` returns explicit `None` (a
  distinguishable signal, not a fabricated benign verdict) when the model/library is missing or
  inference raises; `screen_input` then allows the turn — the deny-list pre-filter already gave
  coarse protection, and blocking all traffic on a model outage would deny service to legitimate
  career questions (§7.4 tunes for low false-positives). Latched so a failing load isn't retried
  every turn. The branch is documented and one-line-flippable to fail-closed.
- **Score/label never leaked.** Category stays `prompt_injection`; the score/label live only in
  the internal `reason` (telemetry). User still only ever sees `REFUSAL_MESSAGE`.
- **`transformers` on the exclusion allowlist**, not the curated install — heavy ML (needs
  torch, already transitive via `sentence-transformers`) and lazily imported.

## How to verify
```
cd backend && . .venv/bin/activate
python3 scripts/check_curated_deps.py          # curated-dep guard OK
ruff check . && ruff format --check .
mypy app/ migrations/
pytest -q
```

## Tests (final step — mandatory)
- `python3 scripts/check_curated_deps.py` → "Curated-dependency guard OK".
- `ruff check` (guardrails + config + tests + script) → All checks passed. `ruff format --check` → clean.
- `mypy app/ migrations/` → Success: no issues found in 159 source files.
- `pytest -q` (full suite) → **887 passed, 83 skipped** (skips are live-DB/ML tests with no
  Postgres/model locally — unchanged from baseline). New `test_injection_classifier.py`: 12
  passed; existing `test_input_guardrails.py` + `test_topic_guardrail.py` still pass unmodified.
- No failures; no test weakened. In the local venv `transformers` is absent, so the default
  classifier fails soft (→ None → fail-open) — existing "allow legitimate message" tests pass via
  fail-open and "block canonical attack" tests pass via the deny-list pre-filter, so no fixtures
  needed changing.

## Self-check
- [x] Meets acceptance criteria (real classifier gate; existing guardrail tests pass unmodified;
  new tests cover classifier block / allow / unavailable-fallback; no paid/unbounded dep; new dep
  curated via exclusion allowlist; ruff/format/mypy/pytest green).
- [x] No secrets committed; guardrails layering (interface before implementation) respected;
  graph wiring untouched.
- [x] Tests/lints pass (pasted above).

## Response to review (revision 2)

**C1 (major) — long input over the 512-token context fails open.** Fixed at the adapter.
`PromptGuardClassifier.classify` now runs `_classify_windows`: the message is split (`_chunk`)
into `chunk_chars`-sized windows (default 2000, constructor-overridable) and each window is
classified; the most-malicious window's `(label, score)` wins, so an injection padded past the
first window is still detected. Belt-and-suspenders: `_build_default_pipeline` now sets
`truncation=True, max_length=512` so even a dense-token window is truncated rather than raising.
The gate now degrades to "scan every window" instead of "raise → None → silently disabled". New
test `test_long_input_is_chunked_and_not_failed_open` uses a fake pipeline that raises on any
call over the window limit, and asserts the over-length input (a) does **not** return `None`
(no fail-open), (b) is flagged via a malicious tail window, (c) is split into >1 call with every
call within the limit. Files: `app/guardrails/injection_classifier.py`,
`tests/test_injection_classifier.py`.

**C2 (minor) — gated default model degrades silently.** Addressed per the reviewer's
"at minimum" path (documentation + visibility), no model swap (avoids an unverifiable download +
new tokenizer dep on a model I can't exercise in the sandbox):
- Documented the gated-access prerequisite (licence-accepted `HF_TOKEN`) and the ungated
  override option (`protectai/deberta-*-prompt-injection`) in both the module docstring and the
  `INJECTION_CLASSIFIER_MODEL` config description.
- Raised the unavailable-latched log from `warning` to **ERROR** with an actionable message
  ("gated models need a licence-accepted HF_TOKEN"), so a misconfigured prod deploy surfaces in
  logs/alerting instead of a one-time warning. The `INJECTION_CLASSIFIER_MODEL` setting already
  lets an operator point at an ungated model without a code change.
Files: `app/guardrails/injection_classifier.py`, `app/config.py`.

**Verification (revision 2):** `ruff check` + `ruff format --check` clean; `mypy` clean on the
changed modules; curated-dep guard OK; full suite **888 passed, 83 skipped** (+1 new test,
existing guardrail tests unmodified). Telemetry nit (JAILBREAK always stamped
`prompt_injection`) noted as non-gating; left as-is to stay scoped.
