# Code review — P6-05-skills-gap · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/services/skills_gap.py:75 | Pure function signature is `compute_skills_gap(role, profile_skills, role_requirements)` — acceptance criteria wrote `compute_skills_gap(profile_skills, role_requirements)`. The extra leading `role` param is a reasonable enhancement (it populates `SkillsGapResult.role`) but deviates from the stated contract. | Optional: keep as-is; no consumer exists yet. Just flagging the divergence for P6-07/P7 awareness. |
| C2 | nit | app/services/skills_gap.py:100 | Role requirements with case-variant duplicate keys (e.g. `"Python"` and `"python"`) could both land in `matched`, producing a duplicate. Dict keys prevent exact dups; case-variant dups are theoretically possible from mining. Harmless (a list, not a set). | None required — non-issue in practice; noted for completeness. |

## Notes
- Correctness: pure `compute_skills_gap` correctly partitions matched/gap, keys matched by the role's requirement vocabulary, orders gap by `(-frequency, -weight, skill.lower())` (deterministic), and defensively coerces malformed JSONB (`frequency`/`weight` → 0.0, non-list `evidence` → []). Blank-skill filtering on both sides is handled. Edge cases (empty profile, empty requirements, malformed spec) are covered by tests.
- Service: degrades gracefully — `profile_missing` short-circuits before any DB access (test asserts `session.statements == []`), `role_profile_missing` on unmined role, both `gap=None`. Never raises, never enqueues mining — matches task/§5.6.
- Layering clean: service depends only on `ProfileStore` port + `repositories.market.get_role_profile` + a local structural `SessionProvider` Protocol; no SQLAlchemy in the service body, no agents-layer import.
- Security: no untrusted input reaching tools, no injection/SSRF surface; `evidence` copied verbatim from the already-mined (PII-stripped per §7.6) role_profile. No API route / Celery task / migration added — matches non-goals.
- Verified locally: `pytest tests/test_skills_gap.py` → 11 passed; `ruff check` clean; `mypy` clean. Fakes (`FakeSession`/`FakeDBProvider`/`FakeExecuteResult`) match the interfaces the service uses.
