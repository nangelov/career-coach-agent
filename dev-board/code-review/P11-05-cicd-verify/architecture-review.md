# Architecture review — P11-05-cicd-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | P11 exit (plan.md) | Full backend+frontend CI command sets green; phase closable | Engineer ran all 7 checks; ruff/format/mypy/pytest + eslint/tsc/jest all exit 0; live-DB variant also green | none |
| A2 | Curated-deps guard (P8-08 / §7.8) | New P11 OTel/Sentry deps correctly curated or allowlisted, not just in pyproject | Guard passes (verified independently, exit 0). CI list (backend-ci.yml:137) == Makefile:58: `opentelemetry-api opentelemetry-sdk sentry-sdk` | none |
| A3 | Dep classification rule | Module-scope light deps → curated; lazy/heavy deps → allowlist | `sentry-sdk` (module-scope guarded import, sentry.py:49) + OTel core curated; `instrumentation-fastapi/-celery` + `exporter-otlp-proto-http` lazily imported inside fns (tracing.py:133/172/184) → correctly on INTENTIONAL_EXCLUSIONS with reasons | none |
| A4 | §8 structure / layering | Verification-only; no source moves | No files changed | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — no source changes, verification-only
- [x] Honors locked decisions — no stack changes; OTel/Sentry are the §7.8 P11 additions
- [x] Interfaces-before-implementations — n/a (T task)
- [x] Budget posture respected — free/OSS OTLP + Sentry SDK; heavy ML stack still excluded from curated venv

## Notes
- Confirmed the design-load-bearing piece independently: `check_curated_deps.py` exits 0, and the CI/Makefile curated lists are byte-identical for the P11 deps. The curated-vs-allowlist split matches the blessed OTel pattern (default-off, lazy exporter/instrumentation; core + guarded Sentry always-on). This is exactly the drift class (FIX-01/02/03/04/09/11) the guard exists to catch, and it is clean.
- Node local v18 vs CI v22 and the `next lint` deprecation notice are informational, out of scope, exit 0 — no design risk.
- P11 (§7.8 observability + Sentry) is design-conformant and closable per plan.md exit criteria.
