"""Minimal, deterministic guardrail heuristics (design §7 — minimal slice).

This is the **cheap, coarse net** the P4 guardrails run — *not* the real P10 classifier. A
single, deliberately-short deny-list of canonical jailbreak / prompt-injection phrasings
("ignore previous instructions", "reveal your system prompt", "you are now DAN", …) backs
**both** directions:

* :func:`screen_input` screens the raw *user message* before any planner/worker work (P4-08),
  blocking a matched turn; and
* :func:`screen_output` screens the responder's *final answer* (§7.3 point 4), **stripping**
  any of those same canonical phrasings that leaked back out of untrusted grounding material
  (a crawled page / CV that told the model "ignore your instructions", echoed into the reply).

Both share the one :data:`_DENY_PATTERNS` list (DRY — no forked second copy). No LLM call, no
ML dependency, no network — pure regex over the text, so either direction is fast enough to
run on every turn.

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
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.state import SafetyVerdict

__all__ = [
    "REFUSAL_MESSAGE",
    "OutputScreenResult",
    "screen_input",
    "screen_output",
]

# ``GuardrailStage`` / ``SafetyVerdict`` are imported lazily *inside* the screen functions
# rather than at module top. ``guardrails`` is a lower layer than ``agents`` (``agents.graph``
# imports this module), and ``app.agents.state`` cannot be imported without running
# ``app.agents.__init__`` — which eagerly loads ``agents.graph`` → ``agents.responder`` →
# back into ``guardrails``. A module-load-time import here would therefore close an import
# cycle; deferring it to call time keeps loading ``guardrails`` free of the ``agents`` package.

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
    from app.agents.state import GuardrailStage, SafetyVerdict

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


#: What a stripped injection fragment is replaced with in the outgoing answer. A visible,
#: neutral marker (rather than silent deletion) so a redaction is auditable and never splices
#: two unrelated clauses into a new, misleading sentence.
_OUTPUT_REDACTION = "[removed]"


@dataclass(frozen=True)
class OutputScreenResult:
    """Outcome of :func:`screen_output` — the (possibly scrubbed) text + its OUTPUT verdict.

    ``text`` is the answer with any matched canonical injection phrasing replaced by
    :data:`_OUTPUT_REDACTION`; it equals the input verbatim when nothing matched. ``modified``
    says whether any replacement happened, so a caller can avoid rewriting state needlessly.
    ``verdict`` is the :class:`~app.agents.state.SafetyVerdict` (``stage=OUTPUT``) stamped onto
    :attr:`~app.agents.state.AgentState.output_safety` for telemetry — it stays ``allowed`` (a
    scrub *neutralises* rather than *blocks*: the answer is still returned, just cleaned).
    """

    text: str
    verdict: SafetyVerdict
    modified: bool


def screen_output(text: str) -> OutputScreenResult:
    """Strip canonical injection phrasings that leaked into the final answer (§7.3 point 4).

    The coarse, deterministic *output* net: it scans ``text`` for the very same canonical
    jailbreak / prompt-injection phrasings :func:`screen_input` blocks on (reusing
    :data:`_DENY_PATTERNS` — one deny-list, both directions) and replaces each verbatim match
    with :data:`_OUTPUT_REDACTION`. This defends against a model echoing an instruction it
    picked up from untrusted grounding material (a crawled page / CV saying "ignore previous
    instructions") straight back into its reply. Anything the deny-list does not recognise is
    passed through unchanged (default-open, mirroring the input heuristic's posture).

    This is a placeholder net; full injection/leakage detection is P10, which replaces it while
    keeping this return contract (see the module docstring).
    """
    from app.agents.state import GuardrailStage, SafetyVerdict

    categories: list[str] = []
    scrubbed = text
    for pattern, category in _DENY_PATTERNS:
        if pattern.search(scrubbed):
            scrubbed = pattern.sub(_OUTPUT_REDACTION, scrubbed)
            if category not in categories:
                categories.append(category)

    if not categories:
        return OutputScreenResult(
            text=text,
            verdict=SafetyVerdict(stage=GuardrailStage.OUTPUT, allowed=True),
            modified=False,
        )

    return OutputScreenResult(
        text=scrubbed,
        verdict=SafetyVerdict(
            stage=GuardrailStage.OUTPUT,
            allowed=True,
            categories=categories,
            reason=f"Output echoed a disallowed pattern ({', '.join(categories)}); redacted.",
        ),
        modified=True,
    )
