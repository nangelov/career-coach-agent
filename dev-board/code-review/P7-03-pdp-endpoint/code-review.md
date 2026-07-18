# Code review — P7-03-pdp-endpoint · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major → **resolved** | `backend/app/agents/pdp_agent.py:226-231,436-500` + `backend/app/services/pdp.py:159-192` | LLM-outage fallback masking generation failure. **Fixed at the P7-01 seam (preferred option):** `_synthesize_sections` returns `dict \| None`; `None` (any `LLMError` or unusable/absent tool call) maps to `_degraded_generation_failed` → `PdpContent(status="generation_failed", …)`. The service's retry loop rejects any `generation_failed` attempt (`continue`), so a persistent outage exhausts the 2-attempt budget → `for…else` → `PdpGenerationFailed` → 502, **no `pdps` row, no PDF**. The masked path is gone. | Done. |
| C2 | minor → **resolved** | `backend/app/services/pdp.py:148-154` | Redundant profile fetch. Kept as a deliberate double-read, documented inline (threading the loaded profile through the shared P6-05 `compute` signature would change a contract used by `roles.py` for one caller's micro-opt; second read is a cheap PK lookup). This was one of the offered alternatives. | Done (accepted). |
| C3 | minor → **resolved** | `backend/app/api/pdp.py` | Profile-less user charged a MESSAGE unit before the 422. Accepted and noted: matches `chat.py`'s charge-before-decline posture; moving the short-circuit ahead would leak profile-existence into the router (breaks Router→Service). This was the offered "accept and note it" alternative. | Done (accepted). |

## Notes
- **C1 verification is genuine, not cosmetic.** `test_pdp_service.py::test_llm_outage_fails_without_persisting_placeholder_plan` drives a `RaisingCompleter` that raises `LLMAllModelsFailedError` on every `complete` call and asserts `PdpGenerationFailed`, `store.saved == []`, and `completer.calls == 2` (initial + bounded retry). The stale agent test that previously encoded the masked behavior (`status == "ok"` on outage) was corrected at the root to `test_llm_failure_reports_generation_failed_status` (asserts `generation_failed`, still fully renderable) — not weakened to pass.
- No status ambiguity: `_pdp_status` only yields `ok`/`role_profile_missing`/`profile_missing`; `generation_failed` is set *only* by `_degraded_generation_failed` after a real synthesis failure, so `PdpGenerated` can never carry it. Thin-but-successful tool calls still go through the existing validation-retry path (unchanged).
- Router mapping intact: `PdpProfileMissing`→422, `PdpGenerationFailed`→502, unexpected→500 catch-all; guests 403'd before any work. Layering (Router→Service→Agent/Repository) unchanged and clean.
- Budget: a MESSAGE charge is retained on synthesis failure (LLM work was attempted, no refund primitive) — a defensible deliberate choice, mirrors `chat.py`.
- Tests green: `pytest tests/test_pdp_service.py tests/test_pdp_agent.py -q` → 15 passed locally; engineer reports full suite 643 passed / 59 skipped (pre-existing live-DB skips). `ruff`/`mypy` clean on changed files.

All revision-1 findings resolved; no new issues introduced. Approving.
