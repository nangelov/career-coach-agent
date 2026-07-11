# Architecture review — FIX-03-pytest-ci-missing-deps · engineer revision 1

## Verdict: CHANGES_REQUESTED

The substantive design posture is fully honored — dependency tiering is correct, both install
lists stay byte-identical, and no heavy/ML lib was added. The only gap is an **incomplete execution
of acceptance criterion #3**: the engineer fixed the workflow's mypy-step comment but left two other
now-false comments that still describe `langgraph` as an excluded / untyped-`Any` lib. Those are the
canonical mypy-posture doc and the load-bearing rationale for a code workaround, so they must be
corrected to match reality before this is done.

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Curated-CI dep tiering (memory ruling `ruling-curated-ci-light-deps`; task §Fix) | Light, always-imported runtime deps curated in; only genuinely heavy ML libs (torch/sentence-transformers/docling) stay absent | `authlib` (already a declared "Auth" dep in `pyproject.toml`) + `langgraph` added; engineer verified `uv pip list` pulls **no** torch/sentence-transformers/docling (langgraph transitives: langchain-core / langgraph-* / pydantic / xxhash) | Conformant. Correct re-classification — see Notes on the langgraph tier shift. |
| A2 | Sync contract (both install lists byte-identical) | Workflow "Install dependencies" list == Makefile `install` target | Both end `... alembic joserfc authlib langgraph`; byte-identical | Conformant. |
| A3 | Keep-CI-light / budget posture (§11; workflow comments) | Free-tier CI excludes the heavy ML stack; paid/heavy behind explicit need only | No ML/CUDA libs added; heavy stack still excluded; non-goals (torch/docling) respected | Conformant. |
| A4 | No app-code/logic change (task non-goals) | `app/security/oidc.py` and `app/agents/graph.py` **logic** untouched | No logic changed; install-list + comments only | Conformant. |
| A5 | Comment accuracy — criterion #3 ("stale langgraph…Any comment corrected") | Every comment that framed langgraph as excluded-and-`Any` updated to reflect it is now installed in CI | Only `.github/workflows/backend-ci.yml` mypy-step comment (L128-133) was fixed. **Two stale instances remain** (see A5a/A5b) | **Required: correct the remaining stale comments.** |
| A5a | ↳ `backend/pyproject.toml` `[tool.mypy]` L70-71 | Comment must not name langgraph as a "treated as Any" example now that it is a real typed dep in CI | Still reads: *"Third-party libs without published type stubs (e.g. **langgraph**, docling) are treated as Any…"* — this is the canonical mypy-posture doc and now actively misinforms | **Required:** drop `langgraph` from this example; keep docling (and torch/sentence-transformers). |
| A5b | ↳ `backend/app/agents/graph.py` L104-105 | `PlannerNode: TypeAlias` rationale must not assert langgraph is absent from CI | Still reads: *"`langgraph` is deliberately absent from CI's curated venv, so `StateNode` resolves to `Any` there"* — inverted premise now that langgraph is installed | **Required (comment only, no logic change — within the non-goal, which scopes to *logic*):** correct the premise. Also assess whether the `TypeAlias`-to-survive-`Any` marker is still needed now that CI resolves langgraph's real types (mypy passed either way — treat as a follow-up, not a forced change). |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — no source moved; install-list + comment change only.
- [x] Honors locked decisions — LangGraph orchestration lib and Authlib OIDC (SSO-only) are exactly the
      v2-locked stack; installing them in CI reinforces, doesn't violate, the locked choices.
- [x] Interfaces-before-implementations — N/A (CI/config task).
- [x] Budget posture respected — free/OSS/self-hosted; heavy ML stack still excluded (A3).
- [ ] Comment/documentation accuracy (criterion #3) — **partially met**; A5a/A5b outstanding.

## Notes (revision 1)
- **langgraph tier re-classification (blessed).** My prior ruling (`ruling-curated-ci-light-deps`,
  from FIX-02) put langgraph in the *heavy/optional, stays curated-absent* tier because in a
  **mypy-only** context its `Any` could be routed around in code. That was the mypy lens. FIX-03 is
  correct that under **pytest** the import is *executed* at collection (no `ignore_missing_imports`
  equivalent), so langgraph **must** be present — and its real transitive footprint is light (no
  torch/CUDA). Re-classifying it as light-and-curated-in is the right call, not a budget-posture
  regression. I am updating my memory ruling to reflect this.
- **Ripple to verify on re-spin (not a new requirement):** with langgraph now actually installed and
  typed in the curated venv, `from langgraph.graph._node import StateNode` (a private module) and
  `StateNode[AgentState, Any]` are now checked against langgraph's **real** types instead of `Any`.
  Engineer's `mypy … Success: no issues found in 75 source files` on the curated venv covers this — good.
  This is why A5b's `TypeAlias` marker may now be redundant; flagging as a follow-up only.
- Everything else (byte-sync, no ML libs, non-goals honored, full suite green on both venvs with/without
  live DB) is solid. Once A5a (and ideally A5b) are corrected, this is an APPROVE.

## Verdict: CHANGES_REQUESTED

---

# Architecture review — engineer revision 2

## Re-review scope
Only the two outstanding comment-accuracy gaps from revision 1 (A5a, A5b). The substantive design
posture (A1–A4) was already APPROVED and is unchanged in this revision.

## Design conformance (revision 2)

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A5a | `backend/pyproject.toml` `[tool.mypy]` comment (canonical mypy-posture doc) | Comment must not name langgraph as a "treated as Any" lib now it is a real typed CI dep | L70-73 now reads: heavy ML libs *"(e.g. docling, sentence-transformers, torch) resolve to Any there… (langgraph IS installed in CI, so its real types apply.)"* langgraph removed from the exclusion example, explicit note added | **Resolved.** |
| A5b | `backend/app/agents/graph.py` `PlannerNode: TypeAlias` rationale | Comment must not assert langgraph is absent from CI / `StateNode` resolves to `Any` | L102-107 rewritten: the inverted premise is gone; it now states the truthful reason — `StateNode` comes from langgraph's private `langgraph.graph._node` module and the `TypeAlias` marker declares the alias unambiguously regardless of how that private symbol is inferred. Marker kept (harmless, intent-explicit; mypy passes either way) | **Resolved.** |

## Cross-cutting checks (revision 2)
- [x] Fits target structure (§8) + layering — comment-only changes; no source moved, no logic touched.
- [x] Honors locked decisions — LangGraph + Authlib remain the v2-locked stack; unchanged.
- [x] Budget posture respected — no libs added/removed in this revision; heavy ML stack still excluded.
- [x] Comment/documentation accuracy (criterion #3) — **now fully met.** Grep confirms the only residual
      "resolve to Any" reference (pyproject.toml L71) is correctly scoped to docling/sentence-transformers/
      torch; the workflow mypy-step comment (L130-131) also states langgraph is now installed. All three
      previously-divergent comment sites are consistent and true.
- [x] Install lists still byte-identical — both workflow L116 and Makefile L50 end `… joserfc authlib langgraph`.

## Notes (revision 2)
- A5b's `TypeAlias` marker was flagged in rev1 as a possible follow-up (redundant now that CI resolves
  langgraph's real types). Engineer kept it and re-scoped the comment to justify it as an intent marker for
  a symbol from a **private** langgraph module. Acceptable — it is harmless, mypy is green either way, and
  keeping it avoids touching logic under the non-goal. No further action.
- No design ripple: this revision changed only three comments; the rev1 substantive verdict stands.

## Verdict: APPROVED
