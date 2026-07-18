# Architecture review — P7-05-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Phase-exit verification is tests-only, no product surface; new artifact lives under `backend/tests/` | Only new file is `backend/tests/test_p7_exit_verification.py`; product edits limited to `ruff format` reflow of P7-01/02 files (untracked, uncommitted) — no logic change | None |
| A2 | Single source of truth (DRY, §5.6 / P7-01 ruling) | Six v1 headings defined once in `app/schemas/pdp.py::SECTION_HEADINGS`; agent + PDF builder derive from it | Confirmed: `SECTION_HEADINGS` defined at `schemas/pdp.py:56`; `agents/pdp_agent.py` and `pdf/builder.py` import + iterate it, no second full copy. Verification asserts this via source scan | None |
| A3 | Layering Router→Service→Agent/Repo (§8) | Router calls Service; Service orchestrates agent/gap/repo; Service never touches DB drivers | `api/pdp.py` router → `services/pdp.py::PdpService` → `generate_pdp` + `SkillsGapService` + resource lookup; no asyncpg/psycopg/sqlalchemy imports in the service (DB via injected provider). Test drives the real layered stack | None |
| A4 | Locked §6: native tool-calling, no ReAct parser | PDP is structured `record_pdp` tool-call; scaffolding structurally impossible | `test_pdp_tool_schema_is_the_forced_six_section_contract` asserts forced tool + six-field schema; `_passes_v1_pdp_gate` confirms no `Action:`/```` ```python ````/`Observation:` leak | None |
| A5 | Grounding in stored profile + skills gap (§5.2 / §5.6 / §5.7) | Gap ranked from `SkillsGapResult`, resources from skill-keyed `list_resources_for_skill` (no embedder), carried structurally deduped by URL | `test_end_to_end...` proves ranked gap reaches the fenced prompt (descending frequency) and `PdpContent.resources` == corpus docs deduped by URL — not model-invented | None |
| A6 | Real-stack / fake-edges posture (P4-10/P5-08/P6-09 precedent) | Compose the real chain; fake only LLM completions + DB sessions; no live HF/Postgres | Faked: `_RecordingSeqCompleter`/`_RaisingCompleter` (LLM) + `FakeSession`/`FakeDBProvider` (DB). Agent fence, forced-tool parse, gap arithmetic, resource lookup, service policy loop, router all real | None |
| A7 | Degradation contract (§5.1 / P7-03) | missing profile→422 no PDF; unmined role→200 best-effort + `X-PDP-Status`; LLM outage→502 no row (rev-2 fix) | All three asserted through the real service+endpoint; `test_llm_outage_...` confirms 2 attempts, no persisted placeholder row (rev-2 fix intact) | None |
| A8 | Budget posture (§11) | free/OSS/self-hosted; in-process, no paid edges introduced | Verification adds no infra/paid dependency; embeddings untouched (resource lookup is skill-keyed, no ML stack) | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — verification is tests-only; drives real layered stack
- [x] Honors locked decisions (no ReAct parser — forced tool call; Postgres+Redis only — DB faked at the provider seam, no new store; SSO-only — auth deps overridden, no password surface; in-process embeddings — untouched)
- [x] Interfaces-before-implementations — fakes injected at the true seams (`LLMCompleter`/router, DB provider, profile/pdp stores), proving the ports are real swap points
- [x] Budget posture respected (free/OSS/self-hosted; no paid edge added)

## Notes
- This is a (T) phase-exit task; my gate is that the verification proves design conformance of the P7 chain, not code-level bug-hunting (code-reviewer owns that). The verification does exactly that: it composes P7-01/02/03 into one story and reports a clear yes on the exit criterion.
- `SECTION_HEADINGS` single-source-of-truth ruling from [[pattern-pdp-agent]] survives intact into the PDF builder (A2) — the P7-01 concern that "deterministic-heading + structured-resource shape must survive into P7-02" is now explicitly regression-guarded by `test_section_headings_not_re_hardcoded_in_agent_or_builder`.
- The P7-03 rev-2 fail-soft ruling (an honest placeholder that passes the length gate must never surface as a 200 PDF) is now covered by a composed end-to-end test — consistent with the fail-soft-must-be-distinguishable posture.
- No design deviation found; no gap to route back to any prior P7 task. The `ruff format` reflow of P7-01/02 files is cosmetic (files still uncommitted P7 work) and does not alter any design seam.
- Follow-up (non-blocking, already logged): the `ResourceLookup`/`SessionProvider` Protocol duplication noted in [[pattern-pdp-agent]] remains; not in scope for a verification task.
