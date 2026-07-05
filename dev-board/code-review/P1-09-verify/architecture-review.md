# Architecture review — P1-09-verify · engineer revision 1

## Verdict: APPROVED

Verification-only task. It changes no source/config (confirmed: `git status` shows only pre-existing
P1-01…P1-08 work). My gate here is whether the **integrated P1 exit criteria conform to the locked v2
design**, and whether the substitute (automated-test) evidence the engineer leans on actually exercises the
design-critical seams. It does. One cheap, env-overridable config-default deviation is logged as a follow-up
(does not block — see Notes / A6).

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Locked decision: no ReAct parser (§6 / CLAUDE.md; plan Phase 1 "output_parser.py is gone") | Zero ReAct/text-parser code in the v2 backend path; native tool-calling only | Independently re-ran the grep: `grep -rniE "Action:|Final Answer:|ReActSingleInputOutputParser|FlexibleOutputParser|PDPOutputParser|output_parser" app/` → exit 1, no hits. Only surviving copy is `legacy-code/output_parser.py` (intentionally-preserved, unreferenced). | None — locked decision honored. |
| A2 | Datastores: Postgres + Redis only, no MongoDB (locked #9, §4) | No Mongo/pymongo/motor anywhere in backend path | Independently ran `grep -rniE "mongo|pymongo|motor" app/` → exit 1, no hits. `config.py` exposes only `DATABASE_URL` (asyncpg Postgres) + `REDIS_URL`. | None. |
| A3 | Mid-stream failover = **resume** on secondary, not restart-with-notice (locked #7, §6.6) | Test proves a mid-stream primary failure resumes the *same* stream on the secondary with no "switching models" notice | `test_llm_router.py::test_stream_midstream_failover_resumes_on_secondary` is the cited evidence; the resume (not restart) semantics is the exact locked behavior. | None — verified via automated test (correctly labeled as such, no live HF egress here). |
| A4 | Failover router present, config-driven, no paid last-resort (locked #4, §6.6, §11) | `LLMRouter.from_settings` reads `LLM_MODELS`/`LLM_PRIMARY`/`LLM_SECONDARY`; free/OSS models only; primary-fail → secondary-serves | 10 green router tests (timeout→failover, 429-retry-then-failover, first-token-deadline failover, breaker, no-failover-on-4xx). `config.py` `LLM_MODELS` doc explicitly forbids a paid last-resort entry. | None. |
| A5 | §8 target structure + Router→Service→Agent/Repo layering | Code lives in the canonical module tree | `ls app/` shows `api/ agents/ llm/ repositories/ ingestion/ memory/ tasks/ guardrails/ services/ pdf/ schemas/ tools/` — all §8 modules present. Chat path is `api/chat.py` → `services/chat.py` → `llm/router.py` + `repositories/redis.py`. | None. |
| A6 | Locked decision #2: primary LLM via **HF Inference Providers (OpenAI-compatible)** | `LLM_BASE_URL` default should target the OpenAI-compatible Inference Providers endpoint (`https://router.huggingface.co/v1`) | `config.py:46` defaults to `https://api-inference.huggingface.co/v1` — the **legacy serverless Inference API host**, which is not the OpenAI-compatible Inference Providers surface the locked decision names. Engineer flagged the same. | **Follow-up (non-blocking):** retarget the `LLM_BASE_URL` config *default* to the OpenAI-compatible Inference Providers endpoint. One-line, env-overridable, no layering/interface change — cheap to fix, not expensive to unwind. Log against P1-01. See Notes. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — verified via `ls app/` and the chat call chain.
- [x] Honors locked decisions (no ReAct parser [A1]; Postgres+Redis only [A2]; mid-stream resume [A3]; no paid last-resort [A4]). SSO-only / in-process embeddings are out of P1 scope (P3/P2) and not regressed by this verify.
- [x] Interfaces-before-implementations — `LLMClient` seam + config-driven `LLMRouter.from_settings` are the swap points the failover tests exercise (consistent with the blessed `llm/` seam).
- [x] Budget posture respected (free/OSS/self-hosted) — `LLM_MODELS` doc forbids paid last-resort; `internet_search` uses self-hostable SearXNG; embeddings in-process.

## Notes
- **A6 rationale for not blocking.** The locked decision is about *which HF surface* the client speaks to
  (OpenAI-compatible Inference Providers). The wrong default host means the walking skeleton would not work
  against real HF out-of-the-box without setting `LLM_BASE_URL` — but (a) this is a verify-only task that
  changed no code, so re-litigating a P1-01-shipped default here would be scope creep; (b) the value is
  centralized and env-overridable, so a correct HF Space secret makes prod work with zero code change; and
  (c) the fix is a one-line default swap — the definition of cheap-to-unwind. Per the gate, that is
  APPROVED-with-logged-follow-up, not CHANGES_REQUESTED. It should be tracked and corrected in a small
  config-only follow-up on P1-01 (default only; do not touch the `llm/` seam), and ideally confirmed against a
  live HF call once network egress / a real token is available. I could not verify the correct endpoint live
  either (no HF egress in this sandbox), so the retarget target should be confirmed against current HF docs at
  fix time.
- **Live-vs-automated labeling is honest and adequate.** No HF egress and no Redis in this sandbox is the same
  posture P0-11-verify took for Docker. The design-critical seams (no-ReAct, mid-stream resume, config-driven
  failover, Postgres/Redis-only) are all either directly greppable (A1/A2/A5) or covered by the cited router
  tests (A3/A4) — the substitute evidence lands on the right seams, not just generic coverage.
- No design risk introduced by this task; it is a conformance snapshot, and the snapshot is clean apart from A6.
