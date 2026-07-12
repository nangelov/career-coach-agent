# Code review — P5-04-cv-upload-endpoint · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major (resolved) | app/api/profile.py:68-89, 131 | **Fixed.** `_read_within_cap` short-circuits on `file.size > max_bytes` (no read at all), then reads in bounded 1 MiB chunks and raises `UploadTooLarge` on overflow so an absent/understated `size` still cannot exceed the cap in RAM. The router calls it before validation/enqueue; the service's post-read length check is now defense-in-depth. Verified in code + `test_read_within_cap_rejects_on_size_before_reading` (fake `.read()` would fail if reached) and `..._rejects_on_overflow_when_size_unknown`. | — |
| C2 | minor (resolved) | app/api/profile.py:130-141 | **Fixed.** Order is now read-under-cap → `service.validate(...)` → `rate_limiter.enforce(UPLOAD, ...)`. A rejected upload no longer consumes the guest's single per-session upload. Verified by `test_rejected_upload_does_not_consume_guest_budget` (415 then 202, only the valid CV enqueued). | — |
| C3 | nit (resolved) | app/tasks/profile_ingest.py:317-343 | **Fixed.** Collaborators are constructed inside the `try`; `redis_client`/`db` start as `None` and the guarded `finally` `aclose`s whatever was opened, so a constructor failure mid-way no longer leaks the Redis client. | — |
| C4 | nit (deferred) | app/tasks/profile_ingest.py | Guest path still constructs the full worker stack before the early-return. Engineer deferred: the collaborators are injected into `run_cv_ingestion` and the guest branch lives inside that seam; folds into the architect's `worker_process_init` singleton follow-up over the same contract (KISS/YAGNI). Reasonable, non-gating. | Optional, later perf pass. |

## Notes
- All previously gating findings (C1 major, C2 minor) are genuinely fixed in the code, not just described in the report. The C1 fix correctly enforces the cap *before* materializing the body (pre-read `file.size` guard plus a bounded chunked read that also protects against a missing/understated `size`), which was the crux of the OOM risk.
- The C2 reorder preserves the abuse-prevention intent: the body is still read under the cap before validation, so no unbounded read precedes rate-limiting — validation is cheap (empty/length/format sniff), so charging after it is safe.
- Layering, typed rejection → 4xx mapping, `submit` re-running `validate` (defense in depth), and the untrusted-input surface reviewed in revision 1 are unchanged and remain sound.
- Verified locally: `uv run --no-sync pytest tests/test_profile_cv_api.py -q` → 9 passed. Engineer reports full suite 380 passed / 45 skipped and green ruff/mypy; no dependency changes this pass (curated-CI posture unchanged). Consistent with the changes reviewed.
- C4 deferral is acceptable and aligns with the architect's independent singleton follow-up; not a blocker for this task.

## Verdict: APPROVED
