# Task P7-01-pdp-agent — PDP agent (structured profile + skills gap + RAG → PDP sections)

- **Phase:** P7   **Status:** ENG   **Tags:** (B)

## Scope
Implement `backend/app/agents/pdp_agent.py`: a PDP-generation agent that takes a user's
**stored structured profile** (P5, `ProfileStore`/`profiles.data`), the **P6 skills gap**
against a target role (`app.services.skills_gap.SkillsGapService` /
`app.schemas.skills_gap.SkillsGapResult`), and RAG-grounded recommendations (shared KB —
`kb_chunks`/learning-resource corpus, `user_id IS NULL`, embedded via
`app.llm.embeddings`/`app.repositories.vector_search`) and produces **structured PDP
sections** matching the v1 section-header contract:

```
## Current Skills Assessment
## Skills Gap Analysis
## Learning Objectives and Milestones
## Recommended Training and Development
## Timeline and Action Steps
## Progress Tracking and KPIs
```

Reference v1 for the shape of the prompt/output (now legacy, gone from the runtime path):
- `legacy-code/app.py` (`pdp_query` template, lines ~308-338) — the section contract.
- `legacy-code/output_parser.py` (`validate_pdp_response`, `PDPOutputParser`) — validation
  rule (≥500 chars, ≥4/6 required headings found) to be ported in **P7-02**, but the agent's
  output must be able to pass it (produce real markdown `##` headings, no ReAct/tool-call
  scaffolding leaking into the text — this is v2's native-tool-calling `LLMClient`/router
  from P1, **no ReAct parser**).

Design constraints:
- **No re-upload.** Input is the already-parsed structured profile (skills/experience/
  education/goals) from `ProfileStore`, not a fresh CV file — that's P7-03's endpoint
  concern, but the agent's interface should take a profile object, not raw file bytes.
- **Grounded, not hallucinated.** Skills-gap items must come from `SkillsGapResult.gap`
  (ranked, with `frequency`/`weight`/`evidence`), and recommended training must be pulled
  from the shared learning-resource corpus (P6-06) via similarity search / skill-keyed
  lookup — cite what's recommended (course title + provider + URL), don't invent courses.
- **Untrusted-content contract (S2, already landed):** CV-derived profile text and any
  crawled/learning-resource text are **data, never instructions** — reuse the existing
  fencing pattern from `agents/rag_agent.py` / `agents/web_searcher.py`, do not invent a new
  one.
- Use the existing `llm/client.py` + `llm/router.py` (native tool-calling / failover) — no
  new LLM plumbing.
- If the target role has no mined `role_profile` yet (skills-gap `status !=
  "ok"`) or the profile is missing, degrade gracefully (produce a best-effort plan from
  profile alone, or a clear error the caller (P7-03) can surface) — do not raise/crash.
- Return a structured result (e.g. a Pydantic model with the six sections as fields, or a
  dict keyed by heading) — not a single opaque blob — so **P7-02**'s PDF builder and
  `pdps.content` (JSONB, already migrated in P2-05) can consume it directly without
  re-parsing markdown.

Look at `agents/rag_agent.py`, `agents/market_agent.py`, `agents/responder.py` for the house
pattern (typed inputs/outputs, no direct DB driver access — go through
`repositories/`/`services/`), and `app/schemas/skills_gap.py` /
`app/services/skills_gap.py` for the exact skills-gap contract to consume.

## Acceptance criteria
- [ ] `agents/pdp_agent.py` exists with a typed entry point (e.g. `generate_pdp(profile,
      skills_gap, career_goal, target_date, ...) -> PdpContent`) producing all six required
      sections grounded in the profile + skills gap + cited learning resources.
- [ ] No ReAct scaffolding/tool-call text can leak into the output (native tool-calling only,
      per P1's locked decision).
- [ ] Unit tests cover: happy path (profile + gap + resources present), degraded paths
      (missing role_profile / missing profile / no learning resources found).
- [ ] Untrusted profile/resource text is fenced as data (matches the S2 contract already used
      elsewhere in `agents/`).

## Design references
- `dev-board/plan.md` — Phase 7 ("PDP Agent: structured profile + skills gap vs the target
  role_profile + RAG-grounded recommendations → structured PDP sections").
- `dev-board/app-design-and-features.md` — §5.2 (PDP feeds dashboard), §5.6 (skills gap →
  PDP), §7.3 (untrusted-content contract).

## Constraints / non-goals
- Do **not** implement the PDF builder (P7-02), the `/api/pdp` endpoint (P7-03), or the
  frontend (P7-04) — those are separate tasks. Keep this task to the agent module + its
  tests.
- Do not touch `pdps` table schema (already migrated, P2-05) unless a genuine gap is found —
  flag it in the report instead of silently changing migrations.
