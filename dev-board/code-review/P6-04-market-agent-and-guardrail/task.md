# Task P6-04-market-agent-and-guardrail — market_agent.py + mining Celery tasks + S3 topic guardrail
- **Phase:** P6   **Status:** ENG   **Tags:** (B)
## Scope
Combines tasks.md P6 bullets 4, 5 and 10 (they share the same `Intent`/`WorkerName` vocabulary and
`agents/planner.py` / `agents/graph.py` edits, so they land as one coherent change):

- **`agents/market_agent.py`** (was `job_agent.py`, design §5.6): normalize a target role → taxonomy baseline
  (query the P6-01 shared KB, `kb_documents.user_id IS NULL`, via `repositories/vector_search.hybrid_search`)
  → mine recent postings for the recency delta → aggregate into a `role_profiles` row (P6-02's `RoleProfile`) →
  embed a summary into `kb_chunks` (`user_id IS NULL`) so future chat turns can retrieve it via RAG.
- **Mining as Celery tasks** (`tasks/market.py` or similar): the pipeline in the module docstring below is a
  **Celery job, never a request-path call** (design §5.6 / §7.5 — "no user-facing turn triggers uncached
  crawling"). All fetched content is **untrusted** (§7.3, reuse `guardrails.untrusted_content.fence_untrusted`
  before any LLM extraction call) and every fetch goes through the **SSRF guard**
  (`app.net.ssrf_guard.build_guarded_client` / `read_capped` — same pattern `agents/web_searcher.py` already
  uses, do not hand-roll a second guarded client).
- **S3 — Topic guardrail** (design §7.4) on the planner's **existing** `Intent` classification, no extra LLM
  call: `OFF_TOPIC` → refuse; `JOB_HUNTING` → **redirect** to market requirements (never lumped in with
  refusal). This naturally lands here because it requires the same `Intent`/`WorkerName` vocabulary rework the
  market agent needs (today's `Intent.JOB_SEARCH` / `WorkerName.JOB_SEARCH` describe v1's dropped "browse job
  listings" concept, not the new market-requirements capability).

**Pipeline (design §5.6):**
```
target role (user-stated)
   → normalize against occupation taxonomy (query P6-01 shared KB)
   → BASELINE role profile (skills, tasks) — zero scraping
   → fetch/crawl N recent postings for that role via the P6-03 Tavily pool + SSRF-guarded crawl
   → strip third-party PII (recruiter name/email/phone) — reuse app.llm.redaction.redact_contact_details
     on posting text BEFORE persisting to job_postings (§7.6); this is in addition to (not instead of) the
     existing automatic LLMRouter egress redaction
   → LLM extraction of requirements per posting (untrusted text, fenced via fence_untrusted — §7.3),
     forced tool-call / constrained schema (mirror the planner's PLANNER_TOOL_SCHEMA + tool_choice pattern —
     no free-text parsing)
   → aggregate: skill → frequency, weight, evidence (job_posting ids / source urls)
   → upsert role_profiles row (global, keyed on canonical_role) + embed a textual summary into kb_chunks
   → refreshed_at stamped
```

**Planner / graph rework:**
- `agents/state.py` `Intent`: replace `JOB_SEARCH` with `MARKET_REQUIREMENTS` (the real capability — "what
  does the market require for role X") and add `OFF_TOPIC` and `JOB_HUNTING` (design §3 / §7.4 intent list:
  *"coaching chat / market-requirements / PDP / CV question / dashboard / off-topic / job-hunting-redirect"* —
  `dashboard` is P8's concern, do not add it here).
- `agents/state.py` `WorkerName`: rename `JOB_SEARCH` → `MARKET_INTEL` (the worker that runs the market-intel
  retrieval — reading an existing/cached `role_profiles` row, *not* running the full mining pipeline inline;
  mining stays a Celery job per §7.5). `_INTENT_WORKERS`: `MARKET_REQUIREMENTS` → `[MARKET_INTEL]`,
  `JOB_HUNTING` → `[MARKET_INTEL]` too (same worker; the **responder** frames the answer as a redirect, not the
  routing — see below), `OFF_TOPIC` → `[]`.
- `agents/graph.py`: replace the `job_search_node` stub with a real node built from `market_agent.py`
  (mirrors how `rag_node`/`web_search_node` were replaced in P4-04/05 — a `make_market_node` factory bound via
  `build_graph(...)`, module-default fails soft when unwired). Add an **`OFF_TOPIC` short-circuit**: after the
  planner classifies `OFF_TOPIC`, skip workers *and* the responder LLM call entirely — reuse exactly the
  `input_guardrail_node` / `route_after_input_guardrail` short-circuit shape (stamp a canned refusal into
  `response`, `finish_reason="off_topic"`, route straight to `OUTPUT_GUARDRAIL`). Do this via a new
  conditional-edge check in (or alongside) `route_after_planner` — do not touch the input-guardrail node itself
  (that stage runs *before* intent is known).
- `agents/planner.py`: update `PLANNER_SYSTEM_PROMPT` to describe the new intents accurately (market
  requirements vs. off-topic vs. job-hunting-redirect, with 1-2 examples each mirroring design §7.4's example
  table) and `_INTENT_MAX_ITERATIONS` for the new values. Tune for **low false-positives** on legitimate career
  questions (design §7.4) — a query like *"How do I close the gap from PM to AI architect?"* must classify as
  `MARKET_REQUIREMENTS` or `chat`, never `OFF_TOPIC`/`JOB_HUNTING`.
- `agents/responder.py`: when `state.plan.intent == JOB_HUNTING`, the composed answer must **redirect** rather
  than pretend to be a listings search — steer the user to the market-requirements answer the `MARKET_INTEL`
  worker already produced (e.g. via the system prompt or an explicit note appended when building the grounding
  block). Keep this minimal — no new LLM call, just prompt/framing.
- Source policy (tasks.md P6 bullet 11 / plan.md "Source policy"): the mining crawler must respect
  `robots.txt` (check before fetching a host, cache per-host for the run), apply a rate limit between requests
  to the same host, and **never fetch `linkedin.com`** (hard-deny, ToS) — add `linkedin.com`/`*.linkedin.com`
  to the SSRF guard's deny-host list or enforce it as an explicit pre-check, whichever composes more cleanly
  with `ssrf_guard.DEFAULT_DENY_HOSTS`. **Put the robots.txt-check + per-host-rate-limit helper in a shared,
  reusable module — `app/ingestion/source_policy.py`** (a small `RobotsChecker`/`HostRateLimiter` pair, no new
  heavy dependency: stdlib `urllib.robotparser` is sufficient) — the P6-06 learning-resource-corpus task (a
  sibling task landing in parallel) needs the **same** robots.txt/rate-limit policy for course-provider crawls
  and will import this module rather than duplicating it. Keep it generic (no market-intel-specific
  assumptions) so it is a clean shared dependency.

## Acceptance criteria
- [ ] `agents/market_agent.py` implements the pipeline above; unit-testable with fake taxonomy/search/LLM
      dependencies (mirrors `rag_agent.py`/`web_searcher.py`'s dependency-injection seams — no hard-coded
      clients).
- [ ] Mining Celery task(s) exist in `tasks/`, follow the existing `tasks/taxonomy.py` / `tasks/profile_ingest.py`
      shape (thin wrapper, testable core, worker-local composition), and are **not** invoked synchronously from
      any request-path code.
- [ ] Every mining fetch goes through the SSRF guard; `robots.txt` is checked; `linkedin.com` is hard-blocked;
      a per-host rate limit is applied. Unit tests cover the deny + robots-check behavior with fakes.
- [ ] Posting text is fenced as untrusted (`fence_untrusted`) before any LLM extraction call; extraction uses a
      forced/constrained tool schema, not free-text parsing.
- [ ] Recruiter contact details are stripped from posting text via `redact_contact_details` before the row is
      persisted to `job_postings`.
- [ ] `role_profiles` rows are upserted keyed on `canonical_role`; a summary is embedded into `kb_chunks`
      (`user_id IS NULL`) via the existing `add_kb_chunk` helper.
- [ ] `Intent`/`WorkerName` rework lands with **no leftover references** to the old `JOB_SEARCH` value/worker
      name anywhere in `agents/`, `api/`, tests (grep to confirm).
- [ ] `OFF_TOPIC` turns short-circuit exactly like a blocked input-guardrail turn (no workers run, no responder
      LLM call, canned refusal). `JOB_HUNTING` turns run the `MARKET_INTEL` worker and the response is
      recognizably a redirect (unit/integration test asserts the intent classification + short-circuit routing;
      exact LLM wording of the redirect is not asserted, only that no listings-style content/tool exists to
      produce one).
- [ ] Planner prompt low-false-positive check: add unit tests for a handful of design §7.4 example queries
      (`"What skills do AI Solution Architects need?"` → not off-topic/job-hunting; `"Find me AI architect jobs
      in Berlin"` → job-hunting; `"Is this rash serious?"` → off-topic) using a fake/scripted `LLMCompleter` (no
      live model call).

## Design references
- dev-board/plan.md: Phase 6, bullets 4-5  ·  Security & privacy sequencing S3 row
- dev-board/app-design-and-features.md §5.6 (full pipeline), §7.3 (untrusted content), §7.4 (topic guardrail,
  example table), §7.6 (third-party PII), §3 (planner intent list)
- Reuse: `app/net/ssrf_guard.py`, `app/guardrails/untrusted_content.py` (`fence_untrusted`),
  `app/llm/redaction.py` (`redact_contact_details`), `app/repositories/vector_search.py` (`hybrid_search`,
  `add_kb_chunk`), `app/repositories/models/market.py` (`RoleProfile`, `JobPosting` from P6-02),
  `app/tools/internet_search.py` / `TavilyPool` (P6-03), `app/agents/planner.py`'s forced-tool-call pattern,
  `app/agents/graph.py`'s `input_guardrail_node` / `route_after_input_guardrail` short-circuit shape

## Constraints / non-goals
- No `GET /api/roles/...` endpoints here (P6-07, next). No skills-gap computation here (P6-05, parallel).
- No learning-resource crawling here (P6-06, parallel) — do not build a second Tavily/crawl mechanism, but do
  not block on it either; these two tasks touch disjoint files.
- Do not add a `dashboard`/`P8` intent — out of scope for this task.
- Extraction happens **once per role** (cache/reuse via `role_profiles`), not per user — do not key anything on
  `user_id`.
