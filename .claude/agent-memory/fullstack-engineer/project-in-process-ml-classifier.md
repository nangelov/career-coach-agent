---
name: project-in-process-ml-classifier
description: Pattern for adding an in-process HF/transformers model (classifier etc.) — ports+adapters, lazy load, injectable seam, fail-soft None, curated-dep exclusion
metadata:
  type: project
---

Adding a small in-process ML model (S8 Prompt-Guard injection classifier; mirrors the P2-06 embedding client).

**Why:** budget posture (§6/§11) — run small models in-process via `transformers`/`sentence-transformers`, no paid inference; but the heavy ML stack (torch) is excluded from the curated CI/dev venv, so tests can never download/run the real model.

**How to apply:**
- Ports+adapters: an ABC interface (e.g. `InjectionClassifier`) + concrete adapter (`PromptGuardClassifier`); the deny-list/`screen_input` seam depends only on the interface.
- **Lazy-load** the model on first use, never at import/`__init__` (defer the `transformers` import inside a factory method). Constructing the adapter must trigger no download.
- **Injectable seam**: a zero-arg `pipeline_factory` / `encoder_factory` ctor arg — tests inject a deterministic fake; production defaults to the lazy real build.
- **Fail-soft = explicit `None`**, not a fabricated benign default (see [[project-fail-soft-must-be-distinguishable]]). Latch "unavailable" so a failing load isn't retried every turn. The caller (`screen_input`) owns the fail-open-vs-closed policy and documents it.
- New dep → add to `pyproject.toml` AND to `INTENTIONAL_EXCLUSIONS` in `scripts/check_curated_deps.py` (heavy/lazy ML libs are excluded from the curated install, not added to it). Run `python3 scripts/check_curated_deps.py` to verify.
- Preserve a sync public contract by adding a keyword-only arg (`screen_input(msg, *, classifier=None)`) — keeps the positional `(str)->Verdict` graph contract and direct-call tests intact; sync model inference is fine from a sync LangGraph node (offloaded to a threadpool).
