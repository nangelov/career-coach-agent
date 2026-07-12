# System-architect memory index

- [Frontend lib/components layering](frontend-lib-components-layering.md) — blessed §8 FE structure: lib/ = DOM-light DI API clients, components/ = React, app/ = routes; wire types mirror Pydantic verbatim
- [Frontend guest-vs-user contract](frontend-guest-vs-user-contract.md) — 200-empty profile (not 404), 403 guest PUT, 429 upload cap, task_id = capability; surface as clear prompts not raw errors
- [Phase-exit verification posture](phase-exit-verification-posture.md) — (T) verify tasks: real stack, fake only outer edges, no product-code change; live/model proofs may skip-gate in CI if disclosed + run green locally
