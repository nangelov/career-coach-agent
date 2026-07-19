# Architecture review — P9-01-message-feedback · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | schema/service-port/repo-adapter/router each in their own module | `schemas/message_feedback.py`, `services/message_feedback.py` (port + test double), `repositories/message_feedback_store.py` (PG adapter), `api/message_feedback.py` (router) | none |
| A2 | §8 layering | Router → Service(port) → Repository; router/service never touch SQLAlchemy | router imports only the `MessageFeedbackStore` port; PG adapter is the sole SQLAlchemy site; mirrors `ProfileStore`/`FeedbackReader` | none |
| A3 | Interface-before-impl | real swappable seam | `MessageFeedbackStore` ABC + `InMemory…` double + `Postgres…` adapter; read methods (`get_for_message`, `list_recent_downvotes`) ready for P9-03 | none |
| A4 | Datastores (Postgres + Redis only) | no new store; row anchored to existing tables | writes existing `message_feedback` (§5.5, shipped P2-03); `build_…` fails loud if PG provider absent (no Redis degrade) | none |
| A5 | §4/§7 data ownership + AuthZ | own-data-only; identity from token not body; guests included | ownership enforced in store via `messages`→`conversations` join; identity from `require_auth`/`CurrentUser`, path param not body; uniform 404 (no missing-vs-not-yours leak, matches `dashboard.py`) | none |
| A6 | Migration conventions (P2-02/03) | Alembic rev chained, no autogen drift | `0009` revises `0008`, pure constraint swap (drop `ix_…` → add `uq_…`), `alembic check` clean; mirrors P8-01 redundant-index refinement | none |
| A7 | Phase fit (P9 capture-only) | capture only; no LangMem/demotion/frontend | endpoint + persistence only; learn-step read seams present but unwired; no UI | none |
| A8 | Budget posture (§11) | free/OSS/self-hosted | in-process, no paid deps | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repo) — store-level owner filter realizes the P5 follow-up I logged (repo-level owner filter for relational rows).
- [x] Honors locked decisions (Postgres+Redis only; SSO-only auth reused via `require_auth`; no new unauthenticated surface).
- [x] Interfaces-before-implementations (`MessageFeedbackStore` port + PG adapter + test double).
- [x] Budget posture respected (free/OSS/self-hosted).

## Notes
- Persisting the *message's* owning `user_id`/`session_id` (not the caller's fresh/Redis-only session) is the correct call to satisfy the `sessions` FK — owner equals caller after the ownership check, so no leak. Sound.
- `MessageRating` `Literal["up","down"]` kept in lockstep with the `ck_message_feedback_rating` check constraint — a single source, good.
- One-row-per-message (`UNIQUE(message_id)`) + `created_at` restamp keeps "recent down-votes" meaningful for P9-03; this shapes P9-03's consumption contract (it reads latest, not full history) — a deliberate, acceptable design boundary.
- No design deviations that would be expensive to unwind.
