# Code review — P10-01-injection-classifier · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major | `app/guardrails/injection_classifier.py` | **FIXED (rev 2).** Long-input fail-open bypass resolved: `classify` now calls `_classify_windows`, which `_chunk`s the message into `chunk_chars` (default 2000) windows and classifies each — most-malicious window wins, so an injection padded past the model context is still detected instead of raising → `None` → silently failing open. Backstop: `_build_default_pipeline` builds with `truncation=True, max_length=512`. Regression test `test_long_input_is_chunked_and_not_failed_open` uses a fake pipeline that raises on over-limit calls and asserts (a) not `None` (no fail-open), (b) `flagged` via a malicious tail window, (c) >1 call each within the limit. Verified passing. | Resolved — no further change required. |
| C2 | minor | `app/config.py:98`, `injection_classifier.py:19-28` | **FIXED (rev 2).** Gated-model silent degradation addressed via the reviewer's "at minimum" path: gated-access prerequisite + ungated `protectai/deberta-*` override documented in both the module docstring and the `INJECTION_CLASSIFIER_MODEL` config description; latched-unavailable load failure raised from `warning` to **ERROR** with an actionable message, so a misconfigured prod deploy surfaces in alerting. Model not swapped (avoids an unexercisable download) — the setting lets an operator point at an ungated model without code change. | Resolved. |

## Notes
- Re-verified locally in the backend venv: `pytest tests/test_injection_classifier.py` → 11 passed, including the new C1 chunking regression test. `transformers` present in both `pyproject.toml` and `check_curated_deps.py::INTENTIONAL_EXCLUSIONS` (unchanged, still correct).
- Structure/layering remain sound: ports-and-adapters mirrors `app/llm/embeddings.py`, lazy import, injectable `pipeline_factory` seam, `screen_input` contract + graph wiring + `SafetyVerdict(stage=INPUT)` shape preserved, score/label never leak to the user.
- **Nit (non-gating):** chunking is character-based (`chunk_chars=2000` ≈ ~500 tokens for latin text); for dense-token content a 2000-char window can exceed 512 tokens and be truncated, dropping the window tail. This is a large improvement over rev-1 fail-open and consistent with approximating the model card's chunking guidance, but token-based windowing (or a smaller default) would close the residual dense-token-tail edge. Not required for this task.
- **Nit (non-gating, carried from rev 1):** a classifier-flagged `JAILBREAK` is always stamped `categories=[prompt_injection]` — internal-telemetry granularity only. Engineer left as-is to stay scoped; agreed.
- Engineer report says "12 unit tests"/"888 passed"; the file contains 11 tests and the suite collected 11 here — a cosmetic count discrepancy, no missing coverage.
