# Task SEC-08-contact-redaction — Contact-detail redaction at the LLM egress boundary
- **Phase:** SEC   **Status:** ENG   **Tags:** (B)

## Scope
Design §6.16 / §7.6: CV data is the most PII-dense document a user owns, and it is sent to a
**third-party inference provider** on every RAG-grounded turn. Before any external LLM call,
strip/pseudonymize the **directly-identifying** fields — **name, email, phone, postal address,
personal URLs/profile links, photo**. **Keep** employers, titles, dates, skills, education — the
substance the coach reasons about. Redaction happens at **one chokepoint in the `llm/` layer**,
not scattered across every agent that happens to build a prompt.

### Where the gap actually is today
- `backend/app/ingestion/structuring.py::ProfileStructurer._build_messages` sends the **raw CV
  Markdown/text** (potentially containing the candidate's name/email/phone/address/links) as the
  user turn to the LLM during CV → `ProfileSchema` extraction. This is the primary, highest-volume
  egress point for CV PII.
- Note: `ProfileSchema` itself (the *output* of that call) already has **no** name/email/phone
  fields — only skills/experience/education/goals — so the *stored* profile is contact-detail-free
  by construction. The gap is the *input* text sent during extraction, and any later flow where
  raw CV/profile text re-enters a prompt (e.g. the RAG worker retrieving the user's own private
  `kb_chunks` — their embedded CV text — and the responder's synthesis call grounding on it,
  design §7.3's `_grounding_block` in `backend/app/agents/responder.py`).
- **`backend/app/llm/router.py::LLMRouter`** is confirmed (by grep) to be the **only** production
  path to a real model call — `structuring.py`, `agents/planner.py`, `agents/responder.py`,
  `tools/base.py`, `tasks/profile_ingest.py` all go through it (directly or via the
  `LLMCompleter`/`LLMResponder` protocols bound to it at the composition root,
  `backend/app/bootstrap.py`). This is the correct single chokepoint the design calls for.

## What to build
1. **A redaction utility**, e.g. `backend/app/llm/redaction.py`, exposing something like
   `redact_contact_details(text: str) -> str` (or operating on a `ChatMessage`/list of messages —
   whichever composes more cleanly with the router). Cover, best-effort and documented as such
   (same "minimal deterministic slice" posture as the P4 input-guardrail heuristics — this is not
   a full NER model, it's regex/heuristic pattern matching, consistent with the OSS/free budget
   constraint):
   - **Email addresses** — reliable regex.
   - **Phone numbers** — a reasonable regex covering common international/US formats
     (don't chase every edge case; document what's covered).
   - **Personal URLs/profile links** — LinkedIn/personal-site-style URLs; a regex for
     `linkedin.com/in/...` and bare personal-looking URLs is enough; don't try to distinguish
     "personal" from "professional" links with certainty — document the heuristic.
   - **Postal address** — best-effort (street-number + street-name + zip-style patterns);
     explicitly document this is unreliable/partial coverage, same honesty standard as the rest
     of this codebase's docstrings.
   - **Name** — hardest without real NER. Acceptable minimal approach: strip an explicit
     `Name:`-labelled line and/or a capitalized "Firstname Lastname"-shaped line near the top of
     a CV (common résumé header pattern) — document this is heuristic/best-effort, not guaranteed.
   - **Photo** — N/A for a text-only chokepoint (nothing here sends raw image bytes to the chat
     LLM today — the VLM-OCR path mentioned in P5 is only *reserved*, not implemented). Note this
     explicitly in `engineer.md` as an accepted current-state limitation, not a gap to fix now.
2. **Wire it into `LLMRouter`** (both `complete` and `stream`, and their shared
   `_complete_one`/underlying call path) so redaction happens **once**, applied to outbound
   message content, regardless of caller. This is the "one chokepoint" the design insists on —
   don't additionally scatter redaction calls into `structuring.py`/`responder.py`/`planner.py`.
   - Decide and document: does redaction apply to *every* message role (system/user/assistant/
     tool), or is it scoped to content that plausibly originated from a CV/profile? Given the
     design's explicit "one place, not scattered" instruction, the simplest and most robust
     approach is to redact **all outbound message content** uniformly at the router — this also
     naturally covers the RAG-grounding path (retrieved CV chunks) and the CV-structuring path
     without needing per-agent tagging. Use your judgment if a genuinely compelling reason
     emerges to scope it more narrowly (e.g. it visibly breaks a normal chat flow), but the
     default expectation is the blanket chokepoint — document whichever you choose and why.
   - Keep this cheap: it runs on every LLM call including the hot chat path, so avoid anything
     pathologically slow (compiled regexes, no external calls).
3. **Confirm employers/titles/dates/skills/education survive.** The redaction must not eat
   ordinary CV content — a phrase like "Senior Engineer at Acme Corp, 2019–2023" must pass
   through unchanged; only the contact-detail categories above are targeted.
4. **Tests**: a CV/message containing name + email + phone + address + LinkedIn URL has all of
   those stripped/masked while employer/title/dates/skills/education content is preserved
   verbatim; a call through `LLMRouter.complete`/`.stream` demonstrably redacts before the
   underlying `client.complete`/`.stream` is invoked (assert on what the fake/mock client
   actually received, not just on the utility function in isolation); ordinary chat messages
   with no PII pass through unchanged (no false-positive mangling of normal text).

## Acceptance criteria
- [ ] A single redaction utility in `backend/app/llm/` covers email, phone, personal URLs,
      best-effort postal address, best-effort name.
- [ ] `LLMRouter` applies it to outbound content on both `complete` and `stream`, before any
      underlying `client` call — verified by a test asserting on what the mocked client receives.
- [ ] Employers/titles/dates/skills/education content is not mangled.
- [ ] No redaction logic is duplicated/scattered into `structuring.py`, `responder.py`,
      `planner.py`, or elsewhere — the router is the only place it happens.
- [ ] Limitations (best-effort address/name coverage, no image/photo redaction) are documented
      in the module docstring, matching the codebase's existing "honest limitations" convention
      (see `guardrails/heuristics.py` for the tone/pattern to follow).

## Design references
- dev-board/app-design-and-features.md §6.16 "CV redaction → contact details only", §7.6 "CV
  data leaves the app — redact contact details before external inference".
- dev-board/tasks.md — SEC block, item **S10**.
- Existing precedent for the "minimal deterministic slice, documented limitations" posture:
  `backend/app/guardrails/heuristics.py`.

## Constraints / non-goals
- Do not build a full ML/NER-based PII detector — regex/heuristic, OSS/free-budget consistent
  with the rest of the project.
- Do not touch the embedding pipeline (`llm/embeddings.py`) — that's a separate concern (stored
  vectors), not the "external inference provider" egress path this task targets. If you believe
  it also needs redaction, note it as a follow-up in `engineer.md` rather than expanding scope.
- Do not attempt photo/image redaction — no current path sends images to the chat LLM.
