# Code review — P1-09-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/app/config.py:45-46 | `LLM_BASE_URL` defaults to `https://api-inference.huggingface.co/v1` — the legacy serverless Inference API, which is not OpenAI-compatible and is being wound down. The locked v2 decision is HF Inference Providers (`https://router.huggingface.co/v1`). A deploy that doesn't override this env var would fail to reach any model, so the walking skeleton silently depends on a Space-secret override. | Not a P1-exit blocker (env-overridable, and this default was set/reviewed in the already-approved P1-01). Retarget the default to `https://router.huggingface.co/v1` in a small config-only follow-up, or have the architect confirm the intended default. Correctly flagged by the engineer; deferred, not fixed, here — appropriate for a verify task. |

## Notes
Verification task (T). I independently re-ran the engineer's evidence rather than re-reviewing P1-01…P1-08 diffs. Everything reproduces exactly as reported — no fabricated or placeholder output.

Reproduced live from `backend/` (`.venv/bin/`):
- `ruff check .` → All checks passed (EXIT 0).
- `ruff format --check .` → 44 files already formatted (EXIT 0).
- `mypy app/` → Success: no issues found in 31 source files (EXIT 0).
- `pytest -q` → 71 passed (EXIT 0).

Exit-criterion evidence confirmed present and correctly labeled:
- **chat → tool → stream → stop:** cited tests exist and match claims — `test_chat_api.py::test_chat_endpoint_streams_sse`, `test_chat_cancel.py::test_cancel_mid_stream_stops_and_emits_cancelled`, `..._between_tool_round_trips_stops_before_next_call`, `..._turn_without_cancel_completes_normally`, plus the 19 tool tests.
- **kill primary → failover:** `test_llm_router.py::test_primary_timeout_fails_over_to_secondary`, `..._primary_429_retries_then_fails_over`, `..._stream_midstream_failover_resumes_on_secondary`, `..._stream_first_token_deadline_fails_over`, `..._client_4xx_is_not_failed_over` all present and green.
- **no ReAct parser:** independently re-ran the grep — `grep -rniE "Action:|Final Answer:|ReActSingleInputOutputParser|FlexibleOutputParser|PDPOutputParser|output_parser" app/` returns zero hits (EXIT 1); `find app/ -iname "*output_parser*"` empty; only `legacy-code/output_parser.py` survives (intentionally preserved, unused). Locked decision honored.

Environment limits are legitimate and honestly documented: no HF egress (`api-inference.huggingface.co` does not resolve here), no Redis on :6379, so the live end-to-end HTTP drive and live-network failover could not be run — substituted with automated-test evidence, matching the P0-11-verify precedent. The report clearly distinguishes "verified live" (baseline suite, grep, FE build) from "verified via existing automated tests" (chat/tool/stream/stop, failover), satisfying the last acceptance criterion.

No tracked source/config files were changed by this task (git status shows only pre-existing P1 branch work) — correct posture for a verification-only task; the engineer did not smuggle in feature changes.

The one non-blocking config-default observation (C1) was surfaced by the engineer, not hidden. It is a real latent issue but out of scope for this exit-verification and belongs to the architect's design call / a config-only follow-up.
