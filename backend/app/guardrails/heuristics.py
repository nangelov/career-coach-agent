"""Minimal, deterministic input-guardrail heuristics (design §7 — minimal slice).

This is the **cheap, coarse net** the P4 input guardrail runs — *not* the real P10
classifier. It screens the raw user message against a small, deliberately-short deny-list
of canonical jailbreak / prompt-injection phrasings ("ignore previous instructions",
"reveal your system prompt", "you are now DAN", …). No LLM call, no ML dependency, no
network — pure regex over the text, so it is fast enough to run on every turn before any
planner/worker/responder work.

**Design posture (read before extending).**

* **Default-open.** Anything the deny-list does not recognise is *allowed*. This is a
  coarse pre-filter meant to minimise false positives on legitimate career questions; it
  only blocks the obvious, canonical phrasings. Real jailbreak/injection detection, PII
  scrubbing, and abuse/off-topic filtering are P10 (`dev-board/tasks.md` P10).
* **Swappable wholesale.** P10 replaces :func:`screen_input` with a real classifier. The
  contract it must preserve is the return type — a :class:`~app.agents.state.SafetyVerdict`
  stamped with ``stage=INPUT`` — which is the shape the graph routes on
  (:func:`app.agents.graph.route_after_input_guardrail`). Keep the deny-list here, small
  and documented, so swapping detection logic does not touch the graph wiring.
* **Never leak the list.** The verdict's ``categories`` / ``reason`` are *internal*
  telemetry (logged, stored on ``AgentState.input_safety``). The user-facing block message
  is the generic :data:`REFUSAL_MESSAGE` — it never echoes which pattern matched.

Length/emptiness is **not** re-checked here: ``ChatRequest.message`` already enforces
``min_length=1`` / ``max_length=8000`` at the schema boundary (design §9), so this module
focuses purely on content heuristics (DRY — no duplicate length guard).
"""

from __future__ import annotations

import re

from app.agents.state import GuardrailStage, SafetyVerdict

__all__ = ["REFUSAL_MESSAGE", "screen_input"]

#: The single, generic user-facing refusal for a blocked turn. Deliberately content-free:
#: it does not repeat the flagged input, does not reveal *why* it was blocked, and does not
#: expose the deny-list — it just declines and redirects to the assistant's actual purpose.
REFUSAL_MESSAGE = (
    "I can't help with that request. I'm here to support your career growth — "
    "feel free to ask me about your job search, CV, skills, or career planning."
)

#: Category labels stamped onto a blocking :class:`SafetyVerdict` (internal telemetry only).
_JAILBREAK = "jailbreak"
_PROMPT_INJECTION = "prompt_injection"

#: The coarse deny-list: ``(compiled pattern, category)``. Kept intentionally small and
#: canonical — this is a placeholder net for P10, not a production filter. Patterns are
#: matched case-insensitively against the raw message. Extend sparingly; a broad pattern
#: that snags legitimate career questions defeats the default-open posture above.
_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # --- prompt injection: subvert the system/prior instructions --------------------- #
    (
        re.compile(
            r"\b(?:ignore|disregard|forget)\b[^.?!]*\b"
            r"(?:previous|prior|above|earlier|preceding|all)\b[^.?!]*\b"
            r"(?:instruction|prompt|message|direction|rule|context)s?\b",
            re.IGNORECASE,
        ),
        _PROMPT_INJECTION,
    ),
    (
        re.compile(
            r"\b(?:ignore|forget|disregard)\b[^.?!]*\b(?:everything|all)\b[^.?!]*\b"
            r"(?:above|before|previous|prior|earlier|preceding|said|written)\b",
            re.IGNORECASE,
        ),
        _PROMPT_INJECTION,
    ),
    (
        re.compile(
            r"\b(?:reveal|show|print|repeat|display|output|expose|tell me)\b[^.?!]*\b"
            r"(?:system\s*prompt|system\s*message|initial\s*instructions?|"
            r"your\s+instructions?|your\s+prompt)\b",
            re.IGNORECASE,
        ),
        _PROMPT_INJECTION,
    ),
    (
        re.compile(
            r"\boverride\b[^.?!]*\b(?:instruction|guideline|rule|programming|safety|"
            r"restriction)s?\b",
            re.IGNORECASE,
        ),
        _PROMPT_INJECTION,
    ),
    # --- jailbreak: coerce an unrestricted / alternate persona ------------------------ #
    (re.compile(r"\bjailbreak\b", re.IGNORECASE), _JAILBREAK),
    (re.compile(r"\bdo\s+anything\s+now\b|\bDAN\s+mode\b", re.IGNORECASE), _JAILBREAK),
    (
        re.compile(r"\byou\s+are\s+now\s+DAN\b|\bact\s+as\s+DAN\b", re.IGNORECASE),
        _JAILBREAK,
    ),
    (re.compile(r"\bdeveloper\s+mode\b", re.IGNORECASE), _JAILBREAK),
    (
        re.compile(
            r"\b(?:pretend|act|behave|roleplay|role-play)\b[^.?!]*\b"
            r"(?:no\s+(?:restrictions?|rules?|filters?|guidelines?|limits?)|"
            r"unrestricted|without\s+(?:restrictions?|rules?|filters?|limits?))\b",
            re.IGNORECASE,
        ),
        _JAILBREAK,
    ),
)


def screen_input(message: str) -> SafetyVerdict:
    """Run the coarse input safety heuristic over ``message`` → an INPUT :class:`SafetyVerdict`.

    Blocks a turn only when the message matches one of the canonical
    jailbreak/prompt-injection patterns in :data:`_DENY_PATTERNS`; otherwise it is
    *allowed* (default-open). On a block the verdict carries the triggered ``categories``
    and an internal ``reason`` (for logs/telemetry) — neither is surfaced to the user, who
    only ever sees :data:`REFUSAL_MESSAGE`.

    This is the minimal P4 slice; P10 replaces it with the real classifier while keeping
    this return contract (see the module docstring).
    """
    categories: list[str] = []
    for pattern, category in _DENY_PATTERNS:
        if category not in categories and pattern.search(message):
            categories.append(category)

    if not categories:
        return SafetyVerdict(stage=GuardrailStage.INPUT, allowed=True)

    return SafetyVerdict(
        stage=GuardrailStage.INPUT,
        allowed=False,
        categories=categories,
        reason=f"Input matched a disallowed pattern ({', '.join(categories)}).",
    )
