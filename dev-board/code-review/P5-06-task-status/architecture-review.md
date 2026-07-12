# Architecture review — P5-06-task-status · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | wire DTO in `schemas/`, mapping policy in `services/`, thin router in `api/` | `app/schemas/jobs.py` (DTO+enum), `app/services/jobs.py` (mapping+ports), `app/api/jobs.py` (router) | Conforms. Correct three-layer split. |
| A2 | §8 layering (Router→Service) | router owns HTTP only; Celery→API mapping isolated & broker-free-testable | Router does auth + `asyncio.to_thread(service.get_status)` only; `map_async_result` is a pure fn; service holds the seam | Conforms. Clean separation; no repository/driver import in the router. |
| A3 | Interfaces-before-impl | Celery must be a swappable seam, not a hard dependency of the service | `AsyncResultLike` / `AsyncResultFactory` Protocol ports; real `AsyncResult` wired only in the composition root (`bootstrap.build_job_status_service`) | Conforms. The only Celery coupling lives at the composition root; service + tests are broker-free. |
| A4 | §8 API table (line 402) | `GET /api/jobs/status/{task_id}` — "Poll async job (OCR/crawl) progress", generic to Celery ids | Router prefix `/api/jobs`, path `/status/{task_id}`; generic mapping (custom states → `in_progress` via meta), no CV-specific naming | Conforms. Genuinely reusable by P6 crawl/OCR producers — no rework needed there. |
| A5 | §5.3 background jobs | progress = Celery state in Redis, polled by UI; no bespoke progress channel | Reads `AsyncResult.state`/`.result` from the existing Redis result backend; surfaces producer `stage`/`message` verbatim | Conforms. Consumes exactly what P5-04's `update_state(meta=...)` emits; no second progress store. |
| A6 | §7 / §9 no-leak | never surface internal exception text/tracebacks to the client | `FAILURE`→`SAFE_FAILURE_MESSAGE`, `REVOKED`→`CANCELLED_MESSAGE`; exception object ignored; test asserts a secret-bearing message is absent from the body | Conforms. |
| A7 | §4 guest posture | guests are Redis-only; guest CV upload still yields a pollable job | Guest (`user_id=None`) polls with its own token; no Postgres touched by this path; test `test_guest_can_poll_own_job` | Conforms. |
| A8 | Datastores (Postgres+Redis only) | no new store | Celery Redis result backend only; no new dependency | Conforms. |
| A9 | §7 AuthZ ("users access only their own data") | own-data-only enforcement | **Capability model:** `require_auth` gates (no anonymous poll) but no task-ownership check — the unguessable UUID4 `task_id` is treated as the bearer capability | **Deviation, accepted with follow-up** (see N1). Softens the §7 own-data posture relative to the app's existing `authorize_session_access` pattern, but it is cheap to tighten later (additive Redis map, no contract change) and the task brief explicitly pre-authorized either choice. Not a gate blocker. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service; service→Celery seam via Protocol)
- [x] Honors locked decisions (Postgres+Redis only; no new store; no ReAct parser / SSO / embeddings surface untouched — N/A here)
- [x] Interfaces-before-implementations (`AsyncResultLike`/`AsyncResultFactory` ports; concrete `AsyncResult` only at the composition root)
- [x] Budget posture respected (no paid deps; reuses the existing Celery/Redis backend)
- [x] Phase fit — belongs to P5 exit ("async, with progress"); deliberately generic so P6 reuses it without premature CV coupling

## Notes

**N1 — AuthZ capability model vs. §7 own-data posture (accepted deviation, live follow-up — do not silently re-bless).**
The endpoint requires auth but does not verify the caller enqueued the `task_id`; any authenticated caller
(guest or user) who possesses a `task_id` can read that job's result, which includes the full structured
**profile PII** (`{profile, persisted, kb_document_id, chunk_count}`). §7 states "users can only read their
own conversations/profiles," and the codebase already has a centralized own-data primitive
(`security/dependencies.py::authorize_session_access`) that this endpoint deliberately does **not** use.

Why I still APPROVE rather than gate:
- The `task_id` is a Celery UUID4 (128-bit, high entropy, unguessable), handed back only to the enqueuing
  request, and the Celery result backend expires results (bounded exposure window).
- The task brief **explicitly pre-authorized either choice** ("treating the `task_id` itself as an
  unguessable bearer capability … Either is defensible; pick one, justify it") — the engineer justified it
  clearly (KISS/YAGNI, and guests have no `user_id` to key on).
- Tightening is **cheap and purely additive**: at enqueue time write `SETEX job_owner:{task_id} <ttl>
  <session_id>` in Redis, and check `current_user.session_id` at poll time (mirroring the guest→session model
  already used elsewhere). No change to the wire contract, the response schema, the service seam, or the
  endpoint shape — so this is not expensive to unwind, which is my gate threshold.

Residual risk to track (this is the classic **capability-URL leakage** surface): the `task_id` travels in the
**URL path**, so it can leak via proxy/access logs, browser history, and `Referer` headers — weaker than an
opaque token in a header/body. Given the result carries profile PII, I want this revisited before the endpoint
is considered production-hardened, and specifically **at P6**, when crawl/OCR producers broaden the set of
result payloads exposed through this same endpoint. Recommended tightening then: the additive Redis
`task_id → session_id` ownership map above, reusing the existing own-data check philosophy. Logged as a live
requirement — do not re-bless the capability-only model silently in P6.

**N2 — module naming overlap (minor, no action).** `api/jobs.py` now hosts async-job *status* polling, while
§8's structure comment earmarks `api/jobs.py` for employment "job search / save / track". The §8 API table
(line 402) does put `/api/jobs/status/{task_id}` under the `/api/jobs` prefix, so the URL is design-correct;
just be aware the two senses of "jobs" (employment vs. background task) will co-habit this router/prefix when
the search/save/track endpoints land. No change required.

**N3 — pre-existing mypy noise** (4 untouched files) is a code-reviewer/tooling concern, out of architecture
scope; the changed files pass `mypy` cleanly per the engineer report.
