# Code review — P7-01-pdp-agent · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/agents/pdp_agent.py:180-202, 427-452 | `generate_pdp`/`_synthesize_sections` docstrings say the function "never raises", but only `LLMError` is caught around `router.complete`. A non-`LLMError` from the router (contract violation / unexpected bug) would propagate out. Matches the planner/responder posture and the `LLMCompleter` contract (router is expected to wrap failures as `LLMError`), so acceptable as-is. | Optional: either broaden the guard (catch a wider exception → `_fallback_sections`) or soften the docstring to "never raises for LLM failures". Not gating. |
| C2 | nit | app/agents/pdp_agent.py:203-205 | `status = _pdp_status(profile, skills_gap)` is computed unconditionally, then discarded on the `profile is None` early-return (which hardcodes `status="profile_missing"` via `_degraded_no_profile`). Harmless dead computation on that branch. | Optional: move the `_pdp_status` call after the `profile is None` check. Cosmetic. |

## Notes
- Correctness: control flow is sound across all four outcomes (ok / role_profile_missing / profile_missing / LLM-failure fallback). `_pdp_status`, `_gap_items`, `_lookup_resources` (short-circuits on empty gap), and `_parse_sections` (None on no-tool-call / decode error / non-dict; missing field → `""`) are each robust and never raise. Verified the parse/dedup/coercion paths against the tests.
- Grounding is real, not just claimed: confirmed `list_resources_for_skill` returns `KbDocument` rows whose `.meta` (via `LearningResource.to_meta`) carries `provider`, `url`, `skill_keys`, so the agent's `meta.get("url")`/`meta.get("provider")` reads resolve against production data — resources are carried structurally on `PdpContent.resources` (deduped by URL, each remembering its matched skill) rather than trusted from free text. Skills-gap prose is driven by `SkillsGapResult.gap`, not the model.
- Security / untrusted-content: reuses the shared `fence_untrusted` helper (no new fence) for the CV-derived profile and the crawled market/learning blocks; the career goal / target date go in the plain trusted user turn — a correct S2/§7.3 application. Native tool-calling is forced (`tool_choice` pinned to `record_pdp`) and the six `## <Heading>` markers are added deterministically by `PdpContent.to_markdown`, so ReAct/tool-call scaffolding is structurally impossible in the rendered output (acceptance #2 met). The tool schema is hand-written and flat (all string properties) — no nested-Pydantic `$defs/$ref` risk.
- DB error in resource lookup is caught broadly and logged with `exc_info`, degrading to general guidance — fail-soft, no crash. Lookups are bounded (`max_gap_skills`, `resources_per_skill`, `_GAP_PROMPT_LIMIT`).
- Layering respected: agent goes through the `learning_resources` repository helper via an injected `ResourceLookup` session provider (structural Protocol) — no SQLAlchemy driver access in the agent body. DI mirrors planner/market seams.
- DRY: `SECTION_HEADINGS` is the single source of truth for the schema fields, the `record_pdp` tool properties, and the markdown headings — cannot drift.
- Acceptance criteria all met: typed `generate_pdp` entry point producing six grounded sections; no scaffolding leak; unit tests cover happy + all three degraded paths (missing profile / unmined role / no resources) plus DB-error, URL-dedup, LLM-failure, partial-args; untrusted text fenced.
- Verified locally: `pytest tests/test_pdp_agent.py` → 9 passed; `ruff check` → clean; `mypy` (strict) on both new modules → Success. Schema untouched for `pdps` (P2-05) as scoped.
