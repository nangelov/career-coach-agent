---
name: pattern-dashboard-schema
description: P8-01/P8-02 blessed dashboard — schema (approved_at DEFERRED, status flip=approval) + CRUD pattern (single aggregate DashboardStore, attribution-in-service, source response-only, guest 403/cross-user 404)
metadata:
  type: project
---

P8-01 (schema-confirm) APPROVED rev 1. Dashboard tables (`goals`/`milestones`/`tasks`/`progress_entries`) from P2-05 confirmed sufficient; one refinement only (migration 0008).

**Blessed rulings (do not re-litigate for P8-02/P8-03):**
- **`approved_at`/`approved_by` = DEFER (settled).** §5.2 "proposed → user approves" is satisfied by the `status` column alone: `status != 'proposed'` means approved; `updated_at` (onupdate=now) captures the approval timestamp; `approved_by` is redundant under strict user-scoping (only the authenticated owner approves own rows). Adding an audit column is additive/feature-scoped — only if a real audit-trail requirement surfaces. Matches P2-05 docstring deferral.
- **Approve/reject flow (P8-02/P8-03)** = flip `status` off `proposed`; pending proposals = `source='ai' AND status='proposed'`. No schema dependency blocks this.
- **`proposed` is in goals/milestones/tasks status vocabularies; progress_entries is stateless** (append-only log, no `status`, no `updated_at`) — correct, not a gap.
- **Streak index:** composite `ix_progress_entries_user_id_created_at (user_id, created_at)` replaced the single-col `user_id` index (leading col still covers FK lookup; dropping the redundant one saves append write cost). Standard, blessed.

**P8-02 (dashboard CRUD + GET /api/dashboard) APPROVED rev 1 — blessed pattern for P8-03/P8-04:**
- **One `DashboardStore` ABC for the whole goal→milestone→task+progress aggregate** (not four narrow ports) — SoC call blessed; InMemory double mirrors DB scoping/cascades; PG adapter uses shared provider, DB CASCADE/SET NULL own deletes; `snapshot()` bulk-read (no N+1).
- **Attribution policy lives in the service, persisted verbatim by store.** Router→`source="user"`; P8-03 tools pass `source="ai"`→status defaults `proposed`. `source` is RESPONSE-ONLY in schemas (never client-sent); human `*Update` status Literals OMIT `proposed` (422 if sent). P8-03 must reuse this service unchanged, not add an AI-write path through the HTTP router.
- **Guest gate = 403 on every dashboard route** (§5.2 dashboard-requires-account); cross-user = uniform 404 (never missing-vs-not-owned leak); owner always from token subject, no path/body user_id.
- Rate-limiting on dashboard CRUD intentionally absent (matches profile.py); acceptable — §11 denial-of-wallet targets LLM/external, not relational CRUD.

**Why:** keeps P8 approve/reject design consistent and avoids re-adding an audit column that YAGNI ruled out.
**How to apply:** when reviewing P8-02 (dashboard repo + GET /api/dashboard) / P8-03 (approve flow), treat status-based approval as the sanctioned design; a new `approved_at` column would need a fresh justification. Dashboard repository seam is P8-02 scope (none existed at P8-01). See [[project-observability-analytics.md]] for P11/P12 renumber context.
