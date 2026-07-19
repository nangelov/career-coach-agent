# Architecture review — P10-06-jailbreak-injection-suite · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | test artifact under `backend/tests/`, single clearly-named module | `backend/tests/test_p10_jailbreak_injection_suite.py` (only file changed) | none |
| A2 | Test drives real seams, not forks | suite exercises production guardrail/graph seams | reuses real `screen_input`/`screen_output`/`fence_untrusted`, real `Responder`, compiled `build_graph`, `GraphTurnStreamer`/`ChatService`; imports P10-04 asserts (DRY) | none — no detection logic duplicated |
| A3 | §7.3 untrusted content (fence + no tool init) | untrusted CV/crawl re-enters fenced as DATA; can never *initiate* a tool call | asserts `--- BEGIN/END REFERENCE MATERIAL ---` + "NOT instructions" fence and `tools is None` on every responder call; full-graph run proves no unrequested fan-out | none |
| A4 | §7.3 point 4 output neutralisation | echoed injection stripped by output net | canonical echo stripped by regex net; non-canonical echo stripped only with classifier — matches buffered `output_guardrail_node` (classifier) vs streaming `screen_output` (no classifier) split | none — test mirrors real production behavior, verified at graph.py:202 vs chat.py:372 |
| A5 | §7.4 topic scoping | off-topic refused vs job-hunting redirected are distinct | off-topic → `OFF_TOPIC_REFUSAL`, responder never called; job-hunting → responder runs redirect; asserted distinct | none |
| A6 | §7 no code-exec (P10-04) | tool set has no exec surface; run-code refused not executed | reuses P10-04 regression guards + graph run proving "run this python" answered as text (no exec tool to reach) | none |
| A7 | Secret/prompt-leak posture ([SEC]) | no real secret/prompt text ever surfaces | `_assert_no_leak` battery: secret-format regexes + live `settings` secret values + system-prompt signatures; P10-03 leakage guard firing asserted | none |
| A8 | Locked v2 decisions | no ReAct parser; LangGraph typed state; Postgres+Redis only; SSO-only; in-process embeddings | test-only; drives LangGraph compiled graph + typed `AgentState`; no new infra, no live LLM/DB/network | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — drives components at their real seams
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only; in-process embeddings)
- [x] Interfaces-before-implementations — doubles implement the real ports (`InjectionClassifier`, responder router/`LLMResponder`, `LLMCompleter`)
- [x] Budget posture respected — no live model/network/DB; fakes only

## Notes
- **Streaming-path non-canonical echo (design follow-up, not a blocker).** Confirmed against source: the buffered `output_guardrail_node` (graph.py:202) runs `screen_output` **with** `default_injection_classifier()`, while the always-on streaming path (chat.py:372) runs `screen_output` **without** it. A non-canonical injection echoed by the model is therefore redacted only in the buffered response, not in streamed token deltas. This is a pre-existing, documented P10-03 trade-off (per-delta model call is prohibitively slow), correctly surfaced by the engineer rather than masked, and correctly not "fixed" inside a test-only task. Recommend the orchestrator log a separate streaming-path hardening follow-up (§7.3 point 4) for P10-03 to decide — out of scope here.
- The suite is a good P10 exit-criterion artifact: one module, six scenarios, driving real seams. No production behavior changed; the intermediate red was a test-bug fix (assertion over-stated production behavior), not a production weakening — the correct call.
