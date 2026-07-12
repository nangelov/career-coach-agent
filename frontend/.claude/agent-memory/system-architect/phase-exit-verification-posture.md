---
name: phase-exit-verification-posture
description: Blessed shape/rigor for phase-exit (T) verification tasks — compose the real stack, fake only outermost edges, live/model proofs may skip-gate in CI
metadata:
  type: project
---

Blessed posture for phase-exit `(T)` verification tasks (P2-09, P4-10, P5-08 precedent).
APPROVE a phase-exit verify when it:
- adds a single composed verification module in `backend/tests/` and changes **no product
  code** (it's a gate, not a feature);
- drives the **real** layered stack (router → service → task/repo, real parsers/agents) and
  fakes **only the true external edges** — model downloads, system binaries (tesseract),
  LLM/HF completions, embeddings (sentence-transformers), the Celery broker/`AsyncResult`, and
  binds producer↔consumer through shared constants (e.g. `STATE_*`) so drift fails;
- maps every plan.md exit-criterion sub-point to a concrete assertion and gives an explicit
  yes/no on the criterion, flagging (not silently patching) any gap in the phase's prior tasks;
- verifies the referenced real symbols exist and are exercised as the real impls, not re-stubbed.

**Accepted limitation (do not gate on it):** the strongest proofs may **skip in a bare CI
env** — `importorskip(...)` for engines the curated venv omits (docling), and a
`DATABASE_URL`-reachable guard for live-Postgres proofs (`vector(4096)`+JSONB, RAG grounding).
This is fine **iff** the skips are honestly disclosed *and* the live/model proofs were actually
run green locally (docker-compose Postgres) with results pasted. Standing non-gating follow-up:
eventually wire a phase-exit CI job around `make test-integration-full` so live proofs gate
somewhere.

**Why:** this environment has no HF creds/live models/managed DB; the seam-heavy architecture
(interfaces-before-impl) is exactly what lets only the outermost edges be faked while the real
tiering/persistence/retrieval decisions still run. Consistency across P2/P4/P5 verifications.

**How to apply:** APPROVE with logged Notes for the CI-skip and any reserved-but-unexercised
seam (e.g. VLM-OCR `vlm.py` — plan.md says "reserve", so absence from a verify is correct
scoping, not a gap). Flag CHANGES_REQUESTED only if a criterion sub-point has no assertion, a
faked edge hides a real seam (e.g. faking both halves of an integration the phase must prove),
or product code was changed under cover of a verify task. See [[frontend-guest-vs-user-contract]].
