# Memory index

- [Async panel race + 202 statuses](pattern-async-panel-race-and-202-statuses.md) — FE roles/profile: secondary-panel resubmit races + role_profile_missing is a 202, not a 200
- [Verification-module guard scans](pattern-verification-module-guard-scans.md) — test_pN_exit_verification source-string guards: naive `)`-split scans + brittle FE contract scans (minor, not blockers)
- [Curated-deps guard + pyproject gap](pattern-curated-deps-guard-and-pyproject-gap.md) — verify curated-CI allowlist honesty via module-scope-vs-deferred greps; joserfc/aiosqlite missing from pyproject deps
