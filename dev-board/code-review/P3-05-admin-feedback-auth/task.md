# Task P3-05-admin-feedback-auth — Replace v1 admin token auth with real admin auth
- **Phase:** P3   **Status:** pending   **Tags:** (B)

## Scope
tasks.md item: "Replace v1 `GET /get-feedback?key=<HF_TOKEN>` with real admin auth."
The v1 endpoint authenticates by matching the HF API token as a query-string `key` — insecure and not a
real access-control model. Design an admin-auth mechanism appropriate for this app (e.g. an `is_admin` flag
on the `users` row, checked via the same session-JWT verify dependency from P3-02, restricting the
equivalent v2 feedback-read endpoint (`GET /api/feedback` or similar per the P7/§7 API table) to admins only).

## Acceptance criteria
- [ ] No endpoint authenticates via a shared secret/token in the query string anymore.
- [ ] The feedback-read endpoint requires an authenticated session belonging to a user flagged as admin.
- [ ] Attempting access as a non-admin (or unauthenticated) is denied.
- [ ] There's a documented way to grant a user admin status (migration/seed/manual DB update — whatever is
      simplest and consistent with the current persistence layer).
- [ ] Tests cover: admin can read; non-admin denied; unauthenticated denied.

## Design references
- dev-board/app-design-and-features.md: §7 ("the v1 `GET /get-feedback?key=<HF_TOKEN>` admin-via-LLM-token pattern is replaced with proper admin auth").
- dev-board/plan.md: P3.

## Constraints / non-goals
- Building a full admin UI/dashboard is out of scope — just the authz mechanism and the endpoint(s).
