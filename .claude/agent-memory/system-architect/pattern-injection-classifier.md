---
name: pattern-injection-classifier
description: P10-01 blessed input jailbreak/injection classifier — in-process Prompt-Guard port/adapter, deny-list demoted to pre-filter, fail-open policy in caller
metadata:
  type: project
---

P10-01 (S8, §7.4) replaced the P4 deny-list *as the input gate* with a real classifier. APPROVED rev 1.

**Blessed shape (reuse verbatim for P10-02 PII scrub / P10-03 output guardrails):**
- `app/guardrails/injection_classifier.py`: `InjectionClassifier` ABC + `PromptGuardClassifier` adapter + injectable `pipeline_factory` seam — mirrors `llm/embeddings.py` port/adapter. Interface-before-implementation is the requirement, not optional.
- In-process `transformers` (Prompt-Guard family), **lazy-loaded on first classify**, deferred import, latched-unavailable. No paid inference dep. Same budget posture as in-process embeddings (§6/§11). `transformers` added to `INTENTIONAL_EXCLUSIONS` in `check_curated_deps.py` + `pyproject.toml`, exactly like `sentence-transformers`.
- Deny-list (`_DENY_PATTERNS`) demoted to a **fast-path pre-filter**; the model is the actual gate. One deny-list backs both `screen_input` and `screen_output` (DRY).
- Config: `INJECTION_CLASSIFIER_MODEL` + `_THRESHOLD` (bounded 0–1) in `config.py`.
- **Graph seam frozen:** `screen_input(str) -> SafetyVerdict` (stage=INPUT) positional contract unchanged; new `classifier=` is keyword-only test seam. `graph.py` route_after_input_guardrail untouched.
- Never leak why/score to user — categories/score internal `reason` telemetry only; user sees generic `REFUSAL_MESSAGE`.

**Why:** Consistency with the embedding-layer precedent (P2-06) and the P4-08 seam contract.
**How to apply:** For P10-02/03 detectors, extend this same port/adapter+lazy-load+curated-exclusion pattern; do not hard-wire a model/SDK into the screen functions, and do not break the SafetyVerdict return contract.

**Open follow-up (logged, not a gate):** fail-open on classifier-unavailable is a documented, one-line-flippable policy in the *caller* (`screen_input`), delegated by the task. Design-conformant; security posture is the code-reviewer's call. Revisit if threat model tightens. See [[project-untrusted-content-contract]] (SEC-02, the output-net side).

**P10-06 exit-criterion artifact (APPROVED rev 1, test-only):** `backend/tests/test_p10_jailbreak_injection_suite.py` — one module, six scenarios, drives real seams (`screen_input/output`, `fence_untrusted`, real `Responder`+compiled graph, reuses P10-04 no-exec asserts). Confirmed the buffered-vs-streaming classifier split is real (graph.py:202 passes classifier; chat.py:372 does not) — test correctly mirrors it, does not "fix" it. Open follow-up (orchestrator's call, out of scope for a test task): harden the streaming path so non-canonical echoed injections are redacted in token deltas, or accept the P10-03 speed trade-off explicitly.

**P10-03 output side (APPROVED rev 1, §7 leakage + §7.3 pt 4):** `screen_output` now 3 stages, `OutputScreenResult` contract kept: (1) P4-08 deny-list echo, (2) new `_LEAKAGE_PATTERNS` = self-contained regex of fixed responder/fence scaffolding, redact-not-block, case/whitespace-tolerant for near-verbatim, (3) opt-in P10-01 classifier segment net via `default_injection_classifier()` — buffered `output_guardrail_node` only, streaming path stays regex-only (per-delta model call too slow). Blessed: classifier reuse (one mechanism), redact-not-block, additive `classifier=` keyword. Logged N1 = leakage patterns duplicate wording owned by responder/untrusted_content (self-contained to dodge guardrails→agents cycle; documented keep-in-sync); same DRY-vs-layering trade as [[project-untrusted-content-contract]]; follow-up = shared frozen-constants module if wording drifts.
