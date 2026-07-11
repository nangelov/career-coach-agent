# Task P3-07-verify — P3 exit verification
- **Phase:** P3   **Status:** pending   **Tags:** (T)

## Scope
tasks.md item: "Guest flow, SSO flow, upgrade-preserves-session, cross-user access denied."
This is the phase-level integration verification pulling together P3-01..P3-06. Write/verify end-to-end
tests (or a documented manual verification, matching how P2-08/P2-09 verify tasks were handled) proving:
1. Guest flow: start guest session → chat up to the rate limit → 11th message denied with upgrade prompt.
2. SSO flow (mocked provider): login redirect → callback → session JWT issued → protected route works.
3. Upgrade-preserves-session: guest chats → upgrades via SSO → same conversation continues, now persisted.
4. Cross-user access denied: user A cannot read user B's conversation/profile via the API.

## Acceptance criteria
- [ ] All four flows above are covered by automated tests (preferred) or a clearly documented manual
      verification script/checklist if some part genuinely requires live provider credentials.
- [ ] Full backend test suite green.
- [ ] `dev-board/plan.md` / `CLAUDE.md` note P3 as landed if instructed by the orchestrator (the orchestrator
      handles checking off tasks.md; this task's job is to prove the exit criteria, not to edit tasks.md).

## Design references
- dev-board/plan.md: P3 exit criteria ("guest and logged-in flows work; guest→account upgrade carries the
  session; access control enforced").
- dev-board/app-design-and-features.md: §4, §6.2, §7.1.

## Constraints / non-goals
- This task should not introduce new endpoints/features — it's verification of P3-01..P3-06's work. If a
  gap is found that requires real implementation changes, flag it in the report rather than silently
  patching around it, so the orchestrator can route a fix to the right prior task.
