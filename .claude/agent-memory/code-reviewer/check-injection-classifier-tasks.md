---
name: check-injection-classifier-tasks
description: Reviewing P10 in-process ML guardrail-classifier tasks (app/guardrails/injection_classifier.py PromptGuardClassifier + screen_input) — context-window vs input max-length silent bypass, gated-model + fail-open compounding
metadata:
  type: project
---

Reviewing P10-01 family: a real in-process HF `transformers` classifier (Prompt-Guard) replacing the P4 deny-list as the input gate, run behind an injectable `pipeline_factory` seam (mirrors `app/llm/embeddings.py`). Structure is usually clean; the bugs are at the model/input boundary and in the failure policy.

**Checks that actually catch things here:**
- **Input length vs model context window (the real bug).** `ChatRequest.message` allows **8000 chars** (`app/schemas/chat.py`), but Prompt-Guard-2-86M has a **512-token** context. If the pipeline is built/called with **no `truncation`**, an over-length message makes `pipeline(text)` raise → caught by the broad `except` in `classify` → returns `None` → `screen_input` **fails open**. So padding an injection past 512 tokens silently bypasses the classifier. Require `truncation=True`/explicit `max_length` (ideally chunk per the model card and flag if any window is malicious) + a long-input test. Major.
- **Fail-open compounding.** Fail-open-on-unavailable is a documented, task-permitted choice — do NOT gate on the policy itself. But note the compounding: long-input error, gated model, or "transformers not installed" all degrade to *silently no classifier*, leaving only the deny-list, with just a one-time `warning` log. Push for a boot-time load check / more visible unavailable signal.
- **Gated model.** `meta-llama/Llama-Prompt-Guard-2-86M` is a **gated HF repo** (needs accepted license + HF_TOKEN with access). In a prod image without access the lazy load raises → latched unavailable → fail open → gate is cosmetic. Flag as minor: document the access prereq or use a non-gated equivalent (e.g. `protectai/deberta-*-prompt-injection`).
- **`_malicious_score` shapes** — confirm it handles binary (`LABEL_0/1`), named (`BENIGN/INJECTION/JAILBREAK`), nested `list[list[dict]]`, and top_k=1 complement (`1 - benign`). Usually covered by tests.
- **Curated-dep guard:** any new heavy ML dep (`transformers`) must be in BOTH `pyproject.toml` and `scripts/check_curated_deps.py::INTENTIONAL_EXCLUSIONS` (lazy import, torch-heavy), like `sentence-transformers`. Run `check_curated_deps.py`.
- The local venv has NO transformers/model, so "pytest green" only proves the fake-pipeline path; the real-model paths (context window, gated download) are un-exercised — reason about them, don't trust the green suite.
