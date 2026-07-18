# Architecture review — P7-03-pdp-endpoint · engineer revision 2

## Verdict: APPROVED

> **Revision 2 (this review).** Re-ran the design gate against the C1 blocker fix (LLM-outage
> fallback text was passing validation and being silently persisted/returned as a 200 PDF instead of
> surfacing as a generation failure) plus the C2/C3 minor dispositions. **No design-conformance
> regression** — the fix stays inside the same three modules (`schemas/pdp.py`, `agents/pdp_agent.py`,
> `services/pdp.py`, all correct per §8), preserves layering and the discriminated-outcome→status
> mapping, and *improves* §5.1 graceful-degradation fidelity. Details in the Revision 2 addendum
> below; the revision-1 conformance table stands unchanged. Verdict remains **APPROVED**.

---

## Revision 1 verdict (unchanged): APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | new code in the right modules | Router `api/pdp.py`, policy `services/pdp.py`, port `services/pdp_store.py`, adapter `repositories/pdp_store.py`, schema `schemas/pdp.py`, wiring `bootstrap.py`/`app_state.py`/`main.py` — every layer in its module | none |
| A2 | Layering (Router→Service→Agent/Repo, §8) | router HTTP-only; service on ports; no DB driver above repo | router does auth/rate-limit/outcome→status only; `PdpService` depends solely on ports (`ProfileStore`, `PdpStore`, `SkillsGapService`, `LLMCompleter`, `ResourceLookup`); SQLAlchemy confined to `PostgresPdpStore` over the shared provider | none |
| A3 | Interfaces-before-implementations | a real seam for PDP persistence | `PdpStore` ABC + `InMemoryPdpStore` double + `PostgresPdpStore` adapter, mirroring `ProfileStore`/`UserStore` | none |
| A4 | House pattern (mirror `roles.py`/`profile.py`) | lazy `build_*_service` cached on `app.state` via `AppStateKeys`; `get_*_service` dep; `require_auth` + guest 403 | `build_pdp_service`, `AppStateKeys.PDP_SERVICE`, `get_pdp_service`, guest 403 pre-work — matches `roles.py` line-for-line | none |
| A5 | Locked: native tool-calling, no ReAct | forced `record_pdp` tool call, no text parser | reuses P7-01 `generate_pdp` (forced tool, `to_markdown` adds headings deterministically); no `output_parser` path touched | none |
| A6 | Locked: Postgres+Redis only, SSO-only, failover router | PG for `pdps`, Redis-backed limiter, failover LLM | `pdps` FK to `users` via shared PG provider; `RateLimitService` (Redis); `LLMRouter.from_settings` (redis-wired breaker) drives the agent | none |
| A7 | Sync-vs-Celery (task §; plan/tasks don't call out Celery) | synchronous default unless a concrete timeout reason | in-request generation, one bounded-token call, seam-to-Celery documented | none |
| A8 | Data ownership (§4) | one profile per user reused, no re-upload; guests can't; PDP owner-scoped | stored-profile-only (`PdpRequest` has no file); guests 403; write keys on verified token subject (`users.id` FK), no body/path `user_id` | none |
| A9 | `pdps` schema (P2-05) | persist per generation, `content` JSONB = `PdpContent` | `PostgresPdpStore.save` inserts a new `Pdp` row per call, `content=model_dump(mode="json")`; migration untouched (no gap) | none |
| A10 | Phase fit (P7) | no P7-04 FE, no P8 dashboard seeding | row persisted as a first-class record for P8 to read later; no goals/tasks wiring, no frontend | none |
| A11 | Budget posture (§11) | free/OSS/self-hosted | reuses in-process embedder path (via SkillsGapService), self-hosted PG/Redis, no paid tier | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo)
- [x] Honors locked decisions (native tool-calling/no ReAct; Postgres+Redis only; SSO-only auth w/ guest 403; failover LLMRouter; sync per plan)
- [x] Interfaces-before-implementations (`PdpStore` port + in-memory + Postgres adapter)
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- **Documented, acceptable divergence from `roles.py`.** `GET /api/roles/{role}/gap` returns `202`+task_id when the role is unmined; `POST /api/pdp` instead degrades to a best-effort profile-only PDF stamped `X-PDP-Status: role_profile_missing`. The task explicitly allowed either; the choice is justified (a PDP is a one-shot download the user asked for *now*) and the unmined state stays machine-readable. Blessed — no re-litigation needed. Missing *profile* correctly stays a hard `422` (no plan is meaningful without a profile).
- **Follow-up (minor, cheap-to-fix-later): LLMRouter construction is duplicated.** `LLMRouter.from_settings(...)` is now built in both `build_chat_service` (bootstrap.py:179) and `build_pdp_service` (bootstrap.py:403). Correctness is fine (circuit-breaker state is shared via Redis keyed on provider index, so two instances are harmless), but this is a DRY seam — a shared `_build_llm_router(app)` helper would centralize it. Logged as a non-blocking cleanup for a future bootstrap-touching task.
- **Trust boundary of `additional_context` is handled correctly.** It is the authenticated user's own typed input, folded into the *trusted* turn text via `_effective_goal` (not the fenced untrusted blocks), consistent with how the P7-01 agent treats `career_goal`/`target_date` and how chat treats the user's own message. The raw `career_goal` (not the context-augmented text) is what's persisted and what drives the skills-gap role lookup — the correct split.
- Consistent with prior rulings: reuses the P6-05 `SkillsGapService` and the P7-01 `ResourceLookup`=`SessionProvider` seam (the DRY dup between those two ports was already logged under P7-01 and is unchanged here).

---

## Revision 2 addendum — C1 fix conformance

| id | area | expected (design ref) | observed (rev 2) | gap |
|----|------|-----------------------|------------------|-----|
| B1 | §8 module placement | fix confined to the owning layers | new `generation_failed` literal in `schemas/pdp.py`; failure surfaced at the P7-01 seam in `agents/pdp_agent.py` (`_synthesize_sections` → `dict \| None`, `_degraded_generation_failed`); rejection policy in `services/pdp.py` retry loop — no new module, no code moved across layers | none |
| B2 | Layering / SoC (§8) | failure classified at the agent seam, policy in the service, HTTP in the router | agent reports the failure via `PdpContent.status`; service branches on it inside the bounded-retry loop → `PdpGenerationFailed`; router unchanged | none |
| B3 | Discriminated-outcome→status mapping (house pattern) | router keeps mapping only the three `PdpResult` variants | router still branches only on `PdpProfileMissing` (422) / `PdpGenerationFailed` (502) / `PdpGenerated` (200). The new `generation_failed` `PdpStatus` is consumed *inside* the service loop and never reaches `PdpGenerated.status`, so `X-PDP-Status` still only ever carries `ok`/`role_profile_missing` | none |
| B4 | §5.1 graceful degradation / task acceptance ("never a broken PDF; clear error; no placeholder row") | real LLM outage → clear error, no persisted row | outage now maps to 502 with no `pdps` row (was a masked 200 + placeholder row in rev 1) — restores v1's "clear error, never a broken PDF" and keeps P8's dashboard from being seeded with placeholder content. A net *improvement* in conformance | none |
| B5 | Locked: native tool-calling, no ReAct | fix does not reintroduce a text-parser path | failure detection keys off the absent/unusable *tool call* (`result.tool_calls` / JSON args), not text parsing; `output_parser` still untouched | none |

**C2 / C3 dispositions (minors).** Both were resolved as documented deliberate trade-offs, not code
changes: C2 keeps the second (cheap, PK-indexed) profile read rather than mutating the shared P6-05
`SkillsGapService.compute` contract for one caller (KISS/YAGNI — correct call, avoids cross-caller
coupling); C3 keeps the up-front message charge before the 422, matching `chat.py`'s "charge before
the model may decline" posture and avoiding a profile-existence leak into the router. Neither affects
design conformance.

**Notes (rev 2).** The `PdpGenerated.status` docstring correctly still enumerates only
`ok`/`role_profile_missing` — consistent with B3, since a `generation_failed` plan can never become
a `PdpGenerated`. The A1/C2 double-read follow-up and the LLMRouter-construction DRY follow-up
(bootstrap.py) both remain open as previously logged non-blocking cleanups; neither is touched by
this revision.

## Verdict: APPROVED
