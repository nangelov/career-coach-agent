# Task P9-04-memory-pii-gdpr-filter — S7: PII redaction + GDPR Art. 9 exclusion before memory writes
- **Phase:** P9   **Status:** ENG   **Tags:** (B) — security items **S7**

## Scope
Gate the P9-03 learn step so **durable `user_memories` are PII-free** and **never contain GDPR
Art. 9 special-category data**, per two [SEC] backlog items:

From `dev-board/tasks.md` (P9):
> **S7 — PII redaction before extraction** (design §7.6): durable `user_memories` are PII-free.
> **S7 — GDPR Art. 9 exclusion filter** (design §7.6): health / disability / ethnicity / religion
> / union / sexuality are **never** made durable (usable within the turn only). A career coach
> *will* receive these.

This is a small, surgical task: wire **two gates** into the existing learn pipeline (P9-03),
not a redesign of it.

### What already exists (read before building)
- `backend/app/llm/redaction.py` — `redact_contact_details(text)` / `redact_messages(...)`, the
  existing deterministic contact-PII redactor (email/phone/URL/address/name), currently used
  only at the **LLM-egress** chokepoint (`LLMRouter`, for CV/RAG content sent to the third-party
  provider — a different concern, §6.16). **Reuse this function** for the "PII redaction before
  extraction" requirement — apply it to the turn text (user + assistant content) **before** it
  is handed to the memory extractor, and/or to each candidate memory's `text` right before
  write, so a redacted extraction never leaks contact details into `user_memories`. Applying at
  both the input (safer, matches the design's "before extraction" wording) and as a defense in
  depth on the final candidate text is fine — pick the point(s) that best guarantee the
  guarantee, and say which in `engineer.md`.
- `backend/app/memory/learn.py` — `MemoryExtractor.propose(...)` is the **documented seam** the
  P9-03 engineer explicitly left for this task ("No PII/GDPR exclusion filter — the single seam
  the next task fills is `MemoryExtractor.propose` (filter its returned candidates)"). Read the
  whole module: `MemoryCandidate`, `LearnConfig`, `run_learn_from_turn`, and the native
  tool-calling `LLMMemoryExtractor`.
- `backend/app/guardrails/` (P4-08 / P10 heuristics module) — the existing deterministic
  deny-list posture (`app.guardrails.heuristics` or similar) to mirror for a **new**, similarly
  cheap, deterministic Art. 9 category classifier: no ML/NER dependency, compiled
  regex/keyword lists per category (health, disability, ethnicity, religion, union membership,
  sexuality/sexual orientation), consistent with the OSS/free budget and this repo's existing
  "coarse heuristic now, real classifier later" posture (the *real* injection classifier is
  P10; this is the same tier of investment for a different category set — a full NER/PII model
  is explicitly out of scope for the free budget).

## Acceptance criteria
- [ ] A new, dedicated module (e.g. `backend/app/memory/gdpr_filter.py`) exposing a pure
      function, e.g. `contains_special_category(text: str) -> bool` (or one that also returns
      *which* category triggered, for logging/telemetry — your call), covering: health,
      disability, ethnicity/race, religion, trade-union membership, sexual
      orientation/sexuality. Deterministic, no I/O, unit-testable in isolation (mirrors
      `app/llm/redaction.py`'s module shape: pure regex/heuristics, documented honest
      limitations).
- [ ] Wired into `MemoryExtractor.propose` (or the point immediately consuming its output in
      `run_learn_from_turn`) so that:
      - any candidate memory whose text trips the Art. 9 filter is **dropped before persistence**
        (never reaches `add_memory`/`update_memory`) — it may still have been *used within the
        turn* (the turn's own response is unaffected; this task does not touch the responder or
        recall path — recall/response synthesis already only reads what's durably stored, so
        "usable within the turn only" is naturally satisfied by not persisting it, not by adding
        new plumbing);
      - every candidate memory's text is passed through `redact_contact_details` (or applied
        upstream on the turn text before extraction — see above) before it is written, so a
        contact detail can never end up verbatim in `user_memories`.
- [ ] Order of operations is documented and sane: redact first, then classify (a redacted string
      must not accidentally hide/alter an Art. 9 signal — verify the two do not fight each other
      with at least one test where both would otherwise fire).
- [ ] Unit tests: a benign preference candidate passes through unchanged in substance; a
      candidate containing an email/phone gets redacted, not dropped; a candidate stating a
      health/disability/religion/ethnicity/union/sexual-orientation fact is dropped entirely
      (never written); a candidate combining both (e.g. "prefers concise advice, mentions being
      on medical leave") — confirm only the correct behavior for the special-category part
      (dropped) without wrongly suppressing an unrelated, separately-extracted benign candidate
      from the same turn.
- [ ] Confirm (by reading, and noting in `engineer.md`) that `job_postings` third-party-PII
      stripping (§7.6, a **different** pipeline — P6 market intelligence) is unaffected; this
      task only touches the P9-03 learn path.

## Design references
- dev-board/app-design-and-features.md: §7.6 "Privacy & data protection (GDPR)" — the exact two
  bullets quoted above (search for "PII redaction in the learning loop" and "GDPR Art. 9 special
  categories").
- dev-board/tasks.md: the [SEC] block's general posture (S1–S16) for how other S-numbered items
  in this repo were scoped/reviewed (see `dev-board/code-review/SEC-*` for precedent — same
  reviewer rigor applies here even though this item lives inside the P9 phase, not the SEC
  block).
- `backend/app/llm/redaction.py`, `backend/app/memory/learn.py` (P9-03).

## Constraints / non-goals
- No change to the LLM-egress redaction chokepoint (`LLMRouter`/`redact_messages`) — that
  boundary already exists and is unrelated to this one (different data flow, different
  decision). Reuse the function; don't move or refactor its call site.
- No ML/NER PII model — deterministic heuristics only, consistent with the free/OSS budget and
  this repo's established posture for "coarse now, real classifier is a later dedicated task"
  categories.
- No changes to recall (P9-02), the memory CRUD API (P9-05), guest personalization (P9-07), or
  retention purge (P9-08).
