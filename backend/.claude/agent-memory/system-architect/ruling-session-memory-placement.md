---
name: ruling-session-memory-placement
description: Where session/conversation memory implementations belong across layers (repositories vs services)
metadata:
  type: project
---

The `SessionMemory` abstraction (load/append conversation history) may keep its **ABC + interim in-memory
impl** in `app/services/` for the P1 walking skeleton, but the **persistent Redis-backed implementation
(P1-05) must land in `app/repositories/redis.py`** per §4 (data ownership) and §8 (repositories = DB access).

**Why:** §8 target structure puts all DB/Redis access behind `repositories/`; services depend on interfaces,
not storage engines. Blessed the interim services/ placement in P1-04 because it is storage-agnostic and no
real store exists yet.

**How to apply:** When reviewing P1-05 (or any task adding a concrete Redis/Postgres-backed store), require the
concrete impl under `repositories/`, with services depending only on the ABC. Do not accept a Redis client
constructed inside a `services/` module as the durable design. See [[pattern-p1-walking-skeleton]].
