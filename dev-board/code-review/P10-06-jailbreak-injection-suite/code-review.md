# Code review — P10-06-jailbreak-injection-suite · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | tests/test_p10_jailbreak_injection_suite.py:250-284 | The `("worker","label","poison")` parametrize passes `label="CV CONTENT"` for the PDP_RESUME row, but the body ignores `label` and hard-asserts `--- BEGIN REFERENCE MATERIAL ---` for both rows. That is actually correct — the real `Responder._grounding_block` fences *all* worker results under the single `REFERENCE MATERIAL` label (responder.py:287) — so the `label` datum is dead and misleading (implies CVs get a distinct fence label). Drop the unused `label` param, or assert against it. | non-blocking |

## Notes
- Test-only change (one new module, no production code touched) — matches the task constraint. Verified `git status`: only `test_p10_jailbreak_injection_suite.py` is new for this task.
- All six required scenarios are exercised against **real** guardrail/graph code, not restated logic: `screen_input` deny-list + injected classifier gate; real `Responder` with a recording router proving `tools=None` on every call (§7.3 point 2); compiled `build_graph` runs proving a blocked/poisoned turn never fans out to an unrequested tool and never reaches the responder LLM; canonical-echo (regex) vs non-canonical-echo (classifier) `screen_output` split; off-topic-refusal vs job-hunting-redirect distinctness; P10-04 no-code-exec asserts reused (imported, DRY).
- Leak battery is genuinely load-bearing: confirmed the three `_SYSTEM_PROMPT_SIGNATURES` fragments actually exist in `RESPONDER_SYSTEM_PROMPT` / `fence_untrusted` output (responder.py:109-114, untrusted_content.py:70), so the redaction assertions have real text to strip rather than passing vacuously. `_live_secret_values()` best-effort-skips blank test-env secrets — acceptable.
- Reused P10-04 tests are imported under `_`-prefixed aliases, so pytest does not re-collect them; DRY reuse means a REPL reintroduction fails in one place.
- The engineer's flagged follow-up (streaming output path runs `screen_output` without the classifier, so a *non-canonical* model-echoed injection is only redacted on the buffered node) is an accurate, pre-existing P10-03 design trade-off — correctly surfaced for the orchestrator rather than silently "fixed" in a test task. Matches my prior note on the per-chunk streaming scrub being strictly weaker than buffered. Not a gate here.
- Verified locally: `ruff check`, `ruff format --check`, `mypy` on the new file all clean; `pytest tests/test_p10_jailbreak_injection_suite.py` → 25 passed; combined P10 guardrail modules → 49 passed.
