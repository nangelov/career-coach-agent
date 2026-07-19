# Engineer report — P9-04-memory-pii-gdpr-filter · Revision 1

## Summary
Wired two deterministic gates into the P9-03 learn pipeline so durable `user_memories` are PII-free
and never carry GDPR Art. 9 special-category data (§7.6). A new pure module classifies Art. 9
categories; the existing `redact_contact_details` is reused for contact-PII. Both run at a single
write-boundary chokepoint (`_apply_candidate`) that every candidate flows through — extractor output
*and* the "avoid X" preference synthesised from a down-vote reason.

## Files changed
- `backend/app/memory/gdpr_filter.py` — NEW. Pure, deterministic Art. 9 classifier:
  `special_category_of(text) -> str | None` (returns the triggered category for telemetry) and
  `contains_special_category(text) -> bool`. Compiled keyword/regex lists per category (health,
  disability, ethnicity/race, religion, trade-union membership, sexuality) — no ML/NER, no I/O.
  Mirrors `app/llm/redaction.py` / `app/guardrails/heuristics.py` posture with documented honest
  limitations.
- `backend/app/memory/learn.py` — added `_gate_candidate()` (redact → classify → keep-redacted /
  drop) and called it at the top of `_apply_candidate`; imported `redact_contact_details` and
  `special_category_of`; updated the module docstring's PII/GDPR note (was "P9-04's gate, not
  here").
- `backend/tests/test_memory_gdpr_filter.py` — NEW. Filter-in-isolation (each category detected,
  benign text not flagged, `union`-in-`reunion`/`European Union` non-collision) + gate-wired-into-
  `run_learn_from_turn` tests.

## Key decisions
- **Gate at the write boundary (`_apply_candidate`), not on `propose`'s return.** `_apply_candidate`
  is the one point every candidate reaches before `add_memory`/`update_memory` — crucially it also
  covers the down-vote-reason candidate, which never passes through the extractor. This is the
  strongest single guarantee that nothing PII/Art. 9 becomes durable (§7.6). Verified by a test that
  a special-category down-vote reason is dropped.
- **Redact first, then classify** (acceptance criterion). Redaction only removes contact PII and
  inserts markers (`[EMAIL REDACTED]` …) that contain no special-category terms, so the two never
  fight. Test `test_redact_first_then_classify_do_not_fight` proves a candidate with both a phone
  number and a health signal is still dropped.
- **Redaction transforms, Art. 9 drops.** A contact-PII candidate is *written with PII removed* (the
  preference survives); a special-category candidate is *dropped entirely* (usable within the turn
  only — this task touches neither responder nor recall, so "in-turn only" holds by simply not
  persisting).
- **No duplicate egress redaction.** PII sent to the extractor LLM is already redacted by the
  `LLMRouter` egress chokepoint (§6.16); this gate is the *durable-store* guarantee, not a second
  copy — so I did not add input-side redaction before `extractor.propose`.
- **Direction of error = over-drop.** The category lists lean slightly broad; a false positive only
  withholds a benign memory from durable storage (no user-visible loss), which is the safe direction
  for Art. 9. `union` requires a multi-word membership phrasing to avoid `European Union` collisions.

## Confirmations (per task)
- `job_postings` third-party-PII stripping is a **different pipeline** (P6 market intelligence):
  `app/agents/market_agent.py` `_crawl_and_redact` → `redact_contact_details` on crawled posting
  text, and `app/repositories/market.py` expects already-stripped text. Untouched by this task.
- The LLM-egress redaction chokepoint (`LLMRouter`/`redact_messages`) is unchanged — the function is
  reused, its call site is not moved.

## How to verify
```
cd backend && source .venv/bin/activate
python -m pytest tests/test_memory_gdpr_filter.py tests/test_memory_learn.py -q
ruff check app/memory/gdpr_filter.py app/memory/learn.py
mypy app/memory/gdpr_filter.py app/memory/learn.py
```

## Tests (final step — mandatory)
- `pytest tests/test_memory_gdpr_filter.py tests/test_memory_learn.py -q` → **46 passed**.
- `ruff check` (3 files) → **All checks passed**; `mypy` (2 source files) → **Success**.
- Full backend suite `pytest -q` → **821 passed, 70 skipped** (skips are pre-existing live-DB /
  optional-dep). No failures.

## Self-check
- [x] Meets acceptance criteria (new pure module; wired into learn path; redact-then-classify;
      benign passes, PII redacted-not-dropped, special-category dropped, benign sibling preserved;
      job_postings pipeline confirmed unaffected).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (pure module below the
      service layer; gate lives inside the existing learn core).
- [x] Tests/lints pass (pasted above).
