# Code review — P9-04-memory-pii-gdpr-filter · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/memory/gdpr_filter.py:70-220 | Over-drop false-positive class is broader than "special category" for a *career* coach specifically: legitimate durable career memories are silently dropped — "wants to become a physical therapist" / "interested in mental health counselling roles" (→ health), "wants a role at a church-tech startup" (→ religion), "targeting LGBT diversity advocacy work" (→ sexuality). Verified by running the filter directly. Task + module docstring explicitly accept over-drop as the safe direction, so not a gate — but occupation/domain mentions are common in this app and a future refinement could exempt occupation-noun contexts. | None required now (documented, accepted). Consider noting the occupation-context class in the module's "honest limitations" and revisit when the real classifier lands. |
| C2 | nit | backend/app/memory/gdpr_filter.py:47 | `SpecialCategory = str` is a bare alias, not a distinct type — no enforcement that returned labels are one of the six constants. Fine for internal telemetry. | Optional: `Literal[...]`/`StrEnum` if these labels ever become an API/telemetry contract. |

## Notes
- Acceptance criteria met: new pure, deterministic, I/O-free module (`special_category_of` / `contains_special_category`) mirroring `redaction.py`/`guardrails` posture; wired at `_apply_candidate` — the single write boundary every candidate reaches before `add_memory`/`update_memory`, so it covers **both** the extractor output *and* the down-vote-reason candidate (confirmed by reading `run_learn_from_turn` line 444 + test `test_downvote_reason_candidate_is_also_gated`).
- Order-of-operations correct and safe: redact → classify. Redaction only substitutes contact PII with `[… REDACTED]` markers that contain no Art. 9 terms, so it can neither hide nor introduce a special-category signal; `test_redact_first_then_classify_do_not_fight` proves a candidate with both a phone number and a health term is still dropped. Redaction *transforms* (memory survives minus PII); Art. 9 *drops* — matches §7.6 "usable within the turn only" (not persisting is the whole mechanism; responder/recall untouched).
- Word-boundary anchoring is sound: `union` collisions (`reunion`, `European Union`) avoided by requiring multi-word membership phrasings; `\b` anchors prevent `ill`-in-`skill` matches. Verified by `test_benign_text_is_not_flagged`.
- Security: no injection/secret surface; deterministic regex only, no network/ML/NER (budget posture honored). Extractor already fences untrusted turn text (`fence_untrusted`) and egress PII redaction stays at the `LLMRouter` chokepoint — this gate is correctly the *durable-store* guarantee, not a duplicate of §6.16.
- `job_postings` P6 pipeline confirmed unaffected (only `learn.py` + new module touched in this task's scope).
- Verified locally: `pytest tests/test_memory_gdpr_filter.py -q` → 28 passed; `ruff check` → clean.
