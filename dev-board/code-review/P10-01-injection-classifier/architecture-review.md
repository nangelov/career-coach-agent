# Architecture review — P10-01-injection-classifier · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Detector lives under `guardrails/` | New `app/guardrails/injection_classifier.py`; `heuristics.py` edited in place; `__init__.py` contract untouched | None |
| A2 | Interfaces-before-implementations | Classifier is a real swap seam, not a hard-wired model/SDK | `InjectionClassifier` ABC + `PromptGuardClassifier` adapter + injectable `pipeline_factory`; `screen_input` depends on the ABC | None — mirrors `llm/embeddings.py` port/adapter shape |
| A3 | Graph seam stable (task §17-19) | `screen_input(str) -> SafetyVerdict` (stage=INPUT) unchanged; graph wiring untouched | `graph.py:166` still calls `screen_input(state.user_message)` positionally; new `classifier=` is keyword-only test seam; `route_after_input_guardrail` unchanged | None |
| A4 | Budget posture (§6/§11) | Free/OSS/self-hosted, in-process, no paid inference dep | In-process `transformers` Prompt-Guard, no per-call API cost; same posture as in-process embeddings (P2-06) | None |
| A5 | Config surface (§ config) | Model name + threshold configurable, curated-dep discipline (P8-08) | `INJECTION_CLASSIFIER_MODEL` / `_THRESHOLD` (bounded 0–1) in `config.py`; `transformers` added to `INTENTIONAL_EXCLUSIONS` + `pyproject.toml`, consistent with `sentence-transformers` | None |
| A6 | No `why` leak to user (§7, existing pattern) | Categories/score internal-only; user sees generic refusal | Label/score live only in `reason` telemetry; user path returns `REFUSAL_MESSAGE`; category stays `prompt_injection` | None |
| A7 | Phase fit (S8) | Replaces the P4 deny-list *as the gate*; deny-list optional pre-filter; no scope creep into P10-02/03 | Classifier is the actual gate; deny-list demoted to fast-path pre-filter; `screen_output` untouched | None |
| A8 | Lazy ML load (import-safety, P2-06 precedent) | No model download at import/CI; deferred `transformers` import | Pipeline built lazily on first `classify`; import deferred inside `_build_default_pipeline`; latched-unavailable | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (guardrails is a lower layer; agents→guardrails only, no reverse coupling)
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only unaffected; in-process ML consistent with embeddings)
- [x] Interfaces-before-implementations (`InjectionClassifier` ABC + adapter + injectable factory seam)
- [x] Budget posture respected (free/OSS/self-hosted, in-process, no paid inference)

## Notes
- **Fail-open on classifier-unavailable is a deliberate, documented policy choice** delegated by the task (§37 "decide and document"). It is defensible: the deny-list pre-filter still runs, and §7.4 tunes for low false-positives, so a model outage should not deny service to legitimate career questions. It is one-line-flippable. From a *design* standpoint this is conformant; whether fail-open is the right *security* posture is the code-reviewer's call. Logged as a follow-up to revisit if the threat model tightens (e.g. deny-list is coarse, so a novel injection during an outage passes) — cheap to flip later, not expensive to unwind, so not a gate.
- `_malicious_score` correctly handles both Prompt-Guard-2 (`LABEL_0`/`LABEL_1`) and original Prompt-Guard (`BENIGN`/`INJECTION`/`JAILBREAK`) label shapes plus the complement-inference path — good forward-compat for a model swap via config (A1/A5).
- Referenced seam-ruling file `ruling-input-guardrail-p4-08-seam.md` does not exist in my memory dir; the P4-08 contract was verified directly against `graph.py` instead (A3). No prior ruling contradicted.
