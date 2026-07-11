# Admin access

Some endpoints are restricted to administrators — currently the feedback-read endpoint
`GET /api/feedback` (the v2 replacement for v1's insecure `GET /get-feedback?key=<HF_TOKEN>`,
which authenticated by matching the LLM API token in the query string).

Admin is a boolean flag on the `users` table (`users.is_admin`), checked at request time by
the `require_admin` dependency against the caller's verified session JWT (P3-02). There is
**no self-service route** that sets this flag — that is deliberate, so no request can
escalate its own privilege. Admin is granted out-of-band by a trusted operator with database
access.

## Prerequisite: the user must have signed in at least once

`is_admin` lives on the user's row, and a row is created only on the user's first SSO login
(Google/LinkedIn). Ask the person to sign in once, then grant them admin.

## Grant admin

Connect to the application database (locally, the `db` service from `docker-compose`) and run:

```sql
-- By email (the address returned by the SSO provider):
UPDATE users SET is_admin = true WHERE email = 'operator@example.com';
```

To confirm:

```sql
SELECT id, provider, email, is_admin FROM users WHERE is_admin = true;
```

## Revoke admin

```sql
UPDATE users SET is_admin = false WHERE email = 'operator@example.com';
```

Because `require_admin` re-checks `is_admin` on every request (no long-lived cached grant in
the token), a revoke takes effect on the user's next request.

## Notes

- A guest session can never be an admin (guests have no `users` row; `require_admin` denies
  them with `403`).
- An unauthenticated request to an admin endpoint is a `401`; an authenticated non-admin is a
  `403`.
- The flag defaults to `false` for every user (migration `0005`), so newly-created accounts
  are never admin by accident.
