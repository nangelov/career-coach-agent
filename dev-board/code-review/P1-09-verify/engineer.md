# Engineer report — P1-09-verify · Revision 1

## Summary

P1 exit-criterion verification (walking skeleton). Goal per `dev-board/plan.md` Phase 1: *"a user can chat,
the model calls a tool, the answer streams token-by-token, stop works, and killing the primary model endpoint
transparently fails over. `output_parser.py` is gone."*

Result table:

| # | P1 exit check | How verified | Result |
|---|---------------|--------------|--------|
| 1 | Backend regression baseline (`ruff check`, `ruff format --check`, `mypy app/`, `pytest -q`) | **Live** — ran in `backend/.venv` | **PASS** (71 passed, 0 lint/type errors) |
| 2 | chat → tool call → token stream → stop/cancel | **Automated tests** (no live HF egress / Redis in this sandbox) | **PASS via tests** (`test_chat_api.py`, `test_chat_cancel.py`, `test_tools.py`) |
| 3 | kill primary → transparent failover to secondary | **Automated tests** (no live HF egress; real token not used) | **PASS via tests** (`test_llm_router.py`) |
| 4 | no ReAct parser / `output_parser.py` in v2 backend path | **Live grep audit** | **PASS** (0 hits in `backend/app/`) |
| 5 | frontend chat page (P1-08) | **Live** `npm run build` + `jest` (no live click-through — no live backend) | **PASS** (build ok, 18 FE tests pass) |

**No source/config defects blocked the exit criteria.** No tracked files were changed by this task. One
non-blocking observation about the default `LLM_BASE_URL` host is flagged below for the reviewers' attention
(it is env-overridable, so it does not block P1).

## Environment constraints (what could NOT be run live here)

This is a sandboxed environment. Probed capabilities:

```
$ getent hosts github.com                → resolves
$ getent hosts huggingface.co            → resolves
$ getent hosts router.huggingface.co     → resolves
$ getent hosts api-inference.huggingface.co → NO DNS (not resolvable here)
$ (redis) exec 3<>/dev/tcp/localhost/6379 → redis NOT reachable on localhost:6379
$ docker info                            → docker up
```

Consequences, and the substitute evidence used (same posture `P0-11-verify` took for Docker-unavailable
checks):
- **No live HF Inference call is possible** — the configured OpenAI-compatible host does not resolve here, and
  I deliberately do **not** exercise the real `HF_API_TOKEN` from `.env`. So the *live* "real conversation
  turn through `POST /api/chat`" and *live* "forced-bad-primary → secondary serves" checks cannot be run.
  Their behavior is proven by the automated suite instead (checks #2/#3 below).
- **No Redis reachable** — `POST /api/chat` / cancel wiring depends on the shared Redis pool
  (`repositories/redis.py`) and the Redis cancel flag; a live end-to-end HTTP drive is therefore not runnable
  here either. Covered by the async unit/integration tests that inject in-memory fakes for Redis/router.
- **No live-backend browser click-through** — frontend verified via production build + Jest instead.

---

## Check #1 — backend regression baseline (LIVE, green)

Run from `backend/` using the project venv (`backend/.venv`, which carries the CI-curated tooling: ruff, mypy,
pytest — see memory note "Local venv is partial").

```
$ .venv/bin/ruff check .
All checks passed!
EXIT=0

$ .venv/bin/ruff format --check .
44 files already formatted
EXIT=0

$ .venv/bin/mypy app/
Success: no issues found in 31 source files
EXIT=0

$ .venv/bin/pytest -q
.......................................................................  [100%]
71 passed in 1.35s
EXIT=0
```

Per-file test breakdown (`pytest --collect-only -q`):

```
  2 tests/test_chat_api.py
 11 tests/test_chat_cancel.py
  5 tests/test_chat_service.py
  1 tests/test_health.py
  4 tests/test_llm_client.py
 10 tests/test_llm_router.py
  9 tests/test_message_id.py
 10 tests/test_session_memory.py
 19 tests/test_tools.py
```

## Check #2 — chat → tool call → stream → stop/cancel (via automated tests)

Not runnable live here (no Redis, no HF egress — see constraints). The integrated behavior is proven by:

- **`test_chat_api.py::test_chat_endpoint_streams_sse`** — drives `POST /api/chat` end-to-end (ASGI, no
  network) and asserts the SSE envelope streams incrementally (`StartEvent` → `TokenEvent`… → `DoneEvent`).
  `test_chat_endpoint_rejects_empty_message` covers the 4xx guard.
- **`test_tools.py`** (19 tests) — the tool layer that a live "what's the date and time right now?" turn would
  hit: `current_date_and_time` schema + execution (`test_current_datetime_default_utc`,
  `..._with_timezone`, `..._bad_timezone_is_graceful`) and the registry round-trip
  (`test_registry_execute_round_trip`, plus graceful handling of unknown tool / bad JSON args / tool
  exceptions). This is exactly the tool-call path the exit criterion's "the model calls a tool" exercises.
- **`test_chat_cancel.py`** (11 tests) — the "stop works" criterion, proven at both boundaries:
  - `test_cancel_mid_stream_stops_and_emits_cancelled` — cancel trips mid-stream; the terminal event is a
    `CancelledEvent` (not `DoneEvent`), fewer tokens stream than scripted, the partial assistant answer is
    persisted, and the Redis cancel flag is cleared on finish.
  - `test_cancel_between_tool_round_trips_stops_before_next_call` — cancel requested after a tool round-trip
    stops the loop before the next model call (`router.calls == 1`), still ending in `CancelledEvent`.
  - `test_turn_without_cancel_completes_normally` — control: no cancel ⇒ terminal `DoneEvent`.
  - Registry/isolation tests confirm the Redis-backed flag has a TTL, is per-session isolated, and stale flags
    are cleared at turn start.

Together these cover the full exit-criterion chain (chat → tool call → token-by-token stream → clean
`cancelled` terminal event), each as a green automated test above.

## Check #3 — kill primary → transparent failover to secondary (via automated tests)

The task itself notes the *actual* primary HF endpoint is a third-party service you cannot kill; and here no
live HF call is possible at all. The router proves failover the way the codebase already does — with a
forced-failing primary client and a healthy secondary — in **`test_llm_router.py`** (10 tests, all green):

- `test_primary_timeout_fails_over_to_secondary` — primary raises `LLMTimeoutError`; the call transparently
  returns the **secondary's** result (`result.model == "secondary"`) and records the primary failure in the
  breaker. This is the direct analogue of "kill primary → next model serves".
- `test_primary_429_retries_then_fails_over` — same-model retry/backoff (3 primary attempts) before failing
  over, distinguishing transient-retry from failover.
- `test_stream_midstream_failover_resumes_on_secondary` — the locked **mid-stream = resume** decision: after
  tokens have streamed, a primary failure resumes on the secondary and the caller sees one continuous stream
  (no restart / no "switching models" notice).
- `test_stream_first_token_deadline_fails_over` — a primary that accepts but never emits a token fails over on
  the first-token deadline.
- `test_circuit_breaker_skips_unhealthy_model`, `test_all_circuits_open_raises`,
  `test_breaker_trips_after_threshold_and_success_resets`, `test_client_4xx_is_not_failed_over` — breaker and
  no-failover-on-4xx policy.

The router is fully config-driven (`LLMRouter.from_settings` reads `LLM_MODELS` / `LLM_PRIMARY_MODEL` /
`LLM_SECONDARY_MODEL`), so the "point the primary at a bad model id" live technique the task describes is
exactly what these tests simulate at the client boundary — clearly labeled here as **verified via existing
automated tests**, not a live network check.

## Check #4 — no ReAct parser / `output_parser.py` in the v2 backend path (LIVE grep, clean)

```
$ cd backend && grep -rniE "Action:|Final Answer:|ReActSingleInputOutputParser|FlexibleOutputParser|PDPOutputParser|output_parser" app/
   (no output)
$ echo $?
1                          # grep exit 1 = zero matches, as expected

$ find app/ -iname "*output_parser*"
   (no output)             # no such file anywhere under backend/app/

$ find /home/.../career-coach-agent -path '*legacy-code*output_parser*'
legacy-code/output_parser.py   # the intentionally-preserved, UNUSED v1 reference copy (P0 "Clean up")
```

Zero ReAct/text-parser hits anywhere in `backend/app/`. The only surviving `output_parser.py` is the
deliberately-kept, unreferenced v1 copy under `legacy-code/` (outside the v2 backend path), consistent with the
P0 "Clean up" note in `dev-board/tasks.md`. Locked decision honored: the v1 ReAct text-parser is gone; the v2
path uses native tool-calling (`app/llm/`, `app/tools/`).

## Check #5 — frontend chat page (P1-08) (LIVE build + tests; no live click-through)

Node 18.19.1 / npm 9.2.0 (Next pinned to 15.x — memory note "Local Node is 18.19.1"). `node_modules` present.

```
$ npm run build
   ▲ Next.js 15.5.19
 ✓ Compiled successfully in 1310ms
   Linting and checking validity of types ...
 ✓ Generating static pages (4/4)
Route (app)                                 Size  First Load JS
┌ ○ /                                    2.82 kB         105 kB
└ ○ /_not-found                            997 B         103 kB
EXIT=0

$ npm test -- --watchAll=false
PASS __tests__/Chat.test.tsx
PASS __tests__/page.test.tsx
PASS __tests__/chatStream.test.ts
Test Suites: 3 passed, 3 total
Tests:       18 passed, 18 total
EXIT=0
```

Production build and all 18 Jest tests (incl. `chatStream.test.ts`, the SSE stream-consumer) pass. A live
click-through against a running backend was **not** run here (no live backend — no Redis / HF egress), so the
browser end-to-end remains unexercised in this environment; its stream-parsing/render logic is covered by the
Jest suite.

## Issues found during verification

**None that block the P1 exit criteria and none requiring a code change.** No tracked files were modified by
this task (`git status` shows only pre-existing P1-branch work from P1-01…P1-08, not authored here).

### Flag (non-blocking) — default `LLM_BASE_URL` host may be stale

- **Observation:** `app/config.py` defaults `LLM_BASE_URL` to `https://api-inference.huggingface.co/v1`. In
  this sandbox `api-inference.huggingface.co` does **not** resolve, while `router.huggingface.co` and
  `huggingface.co` do. HF's current OpenAI-compatible "Inference Providers" endpoint (the locked v2 decision)
  is `https://router.huggingface.co/v1`; `api-inference.huggingface.co` is the legacy serverless Inference API
  (not OpenAI-compatible) and is being wound down.
- **Why not fixed here:** (a) I cannot verify a live HF call in this environment (no egress / not using the
  real token), so I will not change a reviewed P1-01 default I can't test; (b) the value is **env-overridable**
  (`LLM_BASE_URL`) and centralized in config, so a correct HF Space secret makes P1 work in prod without any
  code change — hence non-blocking for this verification. Flagging for the reviewers/architect to confirm the
  intended default and, if desired, retarget it in a small follow-up (config default only).

## How to verify

```bash
# Backend baseline (from backend/, using the CI-curated venv):
cd backend
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app/
.venv/bin/pytest -q                     # 71 passed

# No-ReAct audit:
grep -rniE "Action:|Final Answer:|ReActSingleInputOutputParser|FlexibleOutputParser|PDPOutputParser|output_parser" app/   # exit 1, no output
find app/ -iname "*output_parser*"       # empty

# Frontend (from frontend/):
cd ../frontend
npm run build                            # exit 0
npm test -- --watchAll=false             # 18 passed
```

## Self-check

- [x] Meets acceptance criteria — backend `ruff`/`format`/`mypy`/`pytest` all green (pasted); stream+stop and
      failover covered with clearly-labeled automated-test evidence (no live HF/Redis here); ReAct-parser grep
      audit clean; frontend build + tests green.
- [x] Each exit criterion clearly distinguishes **verified live** (baseline suite, grep, FE build) from
      **verified via existing automated tests** (chat/tool/stream/stop, failover) — with the environment
      reasons documented.
- [x] No secrets committed; no tracked files changed (verification only — Router→Service→Agent/Repo layering
      untouched).
- [x] Tests/lints pass — outputs pasted (backend 71 passed; frontend 18 passed; ruff/mypy clean).

## Response to review (revisions only)

- N/A — revision 1.
