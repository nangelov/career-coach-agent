"""Input/output guardrail heuristics + the real input injection classifier (design §7).

A single, deliberately-short deny-list of canonical jailbreak / prompt-injection phrasings
("ignore previous instructions", "reveal your system prompt", "you are now DAN", …) —
:data:`_DENY_PATTERNS` — backs **both** directions (DRY — no forked second copy):

* :func:`screen_input` screens the raw *user message* before any planner/worker work. As of
  **S8** it is the *real* injection gate: the deny-list is only a cheap fast-path pre-filter,
  and the actual decision is a small in-process Prompt-Guard classifier
  (:mod:`app.guardrails.injection_classifier`). It still returns the same INPUT
  :class:`~app.agents.state.SafetyVerdict` the graph routes on.
* :func:`screen_output` screens the responder's *final answer* (§7.3 point 4 / §7 output
  guardrails). It **redacts** three things: (a) the canonical injection/jailbreak phrasings the
  deny-list recognises, echoed back out of untrusted grounding material (a crawled page / CV
  that told the model "ignore your instructions"); (b) **system-prompt leakage** — distinctive
  fixed scaffolding from the assistant's own instructions / the untrusted-content fence coaxed
  back into the answer (:data:`_LEAKAGE_PATTERNS`); and (c) — when a caller opts in — segments
  the real P10-01 injection classifier flags, so a non-canonical echoed instruction the
  deny-list misses is still caught (no second detection mechanism — the same model that gates
  the input screens the output). This is the P10-03 output guardrail; it keeps the P4-08
  :class:`OutputScreenResult` contract.

The deny-list itself is pure regex — no LLM call, no ML dependency, no network — so it is fast
enough to run on every turn; the classifier the input path adds runs in-process (no per-call
API cost, §6/§11 budget posture) and is lazy-loaded (never at import).

**Design posture (read before extending).**

* **Input gate = classifier; deny-list = pre-filter.** :func:`screen_input` blocks on the
  deny-list *or* on the classifier; a message neither recognises is allowed. If the
  classifier is unavailable it fails **open** to the deny-list — see the function docstring
  for the rationale and how to flip it.
* **Output net is default-open.** :func:`screen_output` redacts what its deny-list, its
  leakage signatures, or (opt-in) the classifier recognise; anything else passes through
  unchanged. A redaction *neutralises* rather than *blocks* — the answer is still returned,
  just cleaned.
* **Never leak the list / score.** A verdict's ``categories`` / ``reason`` are *internal*
  telemetry (logged, stored on ``AgentState.input_safety``). The user-facing block message
  is the generic :data:`REFUSAL_MESSAGE` — it never echoes which pattern matched or the score.

Length/emptiness is **not** re-checked here: ``ChatRequest.message`` already enforces
``min_length=1`` / ``max_length=8000`` at the schema boundary (design §9), so this module
focuses purely on content heuristics (DRY — no duplicate length guard).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.guardrails.injection_classifier import InjectionClassifier, PromptGuardClassifier

if TYPE_CHECKING:
    from app.agents.state import SafetyVerdict

__all__ = [
    "REFUSAL_MESSAGE",
    "OutputScreenResult",
    "default_injection_classifier",
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
#: Output-only category: the model echoed its own system prompt / internal instructions / fence
#: scaffolding back into the final answer (design §7 "block system-prompt leakage").
_SYSTEM_PROMPT_LEAK = "system_prompt_leak"

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


#: System-prompt-leakage signatures (OUTPUT only). Distinctive *fixed scaffolding* fragments
#: that only appear in the assistant's own internal instructions — the responder system prompt
#: and the untrusted-content fence — so if the model is coaxed into repeating its configuration
#: back into the final answer, one of these near-verbatim signatures surfaces. Matched
#: case-insensitively and whitespace-tolerantly (so "near-verbatim" leakage is caught, not only
#: byte-exact), then redacted exactly like :data:`_DENY_PATTERNS`.
#:
#: These mirror scaffolding owned elsewhere (``app.agents.responder.RESPONDER_SYSTEM_PROMPT``,
#: ``app.guardrails.untrusted_content.fence_untrusted``) but are kept **self-contained** here —
#: as ``_DENY_PATTERNS`` is — rather than imported: ``guardrails`` is a *lower* layer than
#: ``agents`` (importing the responder would close an import cycle). Keep them in sync if that
#: fixed wording changes; the structural fence markers are label-agnostic, so they survive a
#: label rename. Signatures are deliberately long/specific to avoid snagging ordinary prose.
_LEAKAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # --- untrusted-content fence scaffolding (fence_untrusted) ------------------------- #
    (re.compile(r"---\s*(?:BEGIN|END)\s+[A-Z][A-Z0-9 ]*?\s*---"), _SYSTEM_PROMPT_LEAK),
    (
        re.compile(r"treat\s+it\s+strictly\s+as\s+untrusted\s+data", re.IGNORECASE),
        _SYSTEM_PROMPT_LEAK,
    ),
    (
        re.compile(r"is\s+not\s+from\s+the\s+user\s+and\s+is\s+not\s+instructions", re.IGNORECASE),
        _SYSTEM_PROMPT_LEAK,
    ),
    # --- responder persona / synthesis brief (RESPONDER_SYSTEM_PROMPT) ----------------- #
    (
        re.compile(r"you\s+are\s+a\s+helpful,?\s+encouraging\s+career\s+coach", re.IGNORECASE),
        _SYSTEM_PROMPT_LEAK,
    ),
    (
        re.compile(r"when\s+reference\s+material\s+is\s+provided\s+below", re.IGNORECASE),
        _SYSTEM_PROMPT_LEAK,
    ),
    (re.compile(r"do\s+not\s+fabricate\s+citations", re.IGNORECASE), _SYSTEM_PROMPT_LEAK),
)

#: Sentence/line boundary used to segment the final answer for the (opt-in) classifier net —
#: a capturing split so the delimiters are preserved and the answer can be re-joined verbatim
#: with only the flagged segments swapped out. Segments with no letters (bare punctuation /
#: whitespace) are never classified.
_OUTPUT_SEGMENT_SPLIT = re.compile(r"([.!?\n]+\s*)")


#: Lazily-built default classifier singleton backing :func:`screen_input` when a caller does
#: not inject its own. Constructing it loads **no** model (the pipeline is lazy — see
#: :mod:`app.guardrails.injection_classifier`), so building it here is cheap and import-safe.
_DEFAULT_CLASSIFIER: InjectionClassifier | None = None


def _default_classifier() -> InjectionClassifier:
    """Return the process-wide default injection classifier, constructing it once (lazily)."""
    global _DEFAULT_CLASSIFIER
    if _DEFAULT_CLASSIFIER is None:
        _DEFAULT_CLASSIFIER = PromptGuardClassifier()
    return _DEFAULT_CLASSIFIER


def default_injection_classifier() -> InjectionClassifier:
    """The process-wide default injection classifier — shared by the input gate and the
    buffered-output net (:func:`app.agents.graph.output_guardrail_node`).

    Constructing it loads **no** model (the pipeline is lazy), so calling this on the buffered
    output path is cheap and import-safe. Exposed as the public seam so the output node reuses
    the *same* classifier the input gate uses (one detection mechanism, not two) rather than
    reaching into the private singleton.
    """
    return _default_classifier()


def screen_input(message: str, *, classifier: InjectionClassifier | None = None) -> SafetyVerdict:
    """Screen ``message`` for jailbreak / prompt-injection → an INPUT :class:`SafetyVerdict`.

    Two stages (S8, design §7.4):

    1. **Fast-path deny-list pre-filter** — the cheap, deterministic :data:`_DENY_PATTERNS`
       regex net catches the obvious canonical phrasings before any model call. A match
       blocks immediately (no classifier invocation).
    2. **Real classifier gate** — otherwise the in-process Prompt-Guard classifier
       (:class:`~app.guardrails.injection_classifier.InjectionClassifier`) is the actual
       gate: a message it flags (malicious probability ``>=`` threshold) is blocked.

    **Failure mode — fail *open*.** If the classifier is *unavailable* (``classify`` returns
    ``None`` — model/library missing, download or inference failed) the turn is **allowed**.
    Rationale: the deny-list pre-filter above still provides coarse protection, and blocking
    *all* traffic on a model outage would deny service to legitimate career questions (§7.4
    tunes for low false-positives). The choice is deliberate and documented; flip the
    ``verdict is None`` branch to fail closed if the posture changes.

    On a block the verdict carries the triggered ``categories`` and an internal ``reason``
    (logs/telemetry) — neither is surfaced to the user, who only ever sees
    :data:`REFUSAL_MESSAGE` (the score / matched pattern is never leaked).

    Args:
        classifier: Optional injected classifier (test seam). ``None`` → the process-wide
            lazy default (:func:`_default_classifier`). The positional ``(message) ->
            SafetyVerdict`` contract the graph routes on is unchanged.
    """
    from app.agents.state import GuardrailStage, SafetyVerdict

    # Stage 1: cheap deterministic pre-filter.
    categories: list[str] = []
    for pattern, category in _DENY_PATTERNS:
        if category not in categories and pattern.search(message):
            categories.append(category)
    if categories:
        return SafetyVerdict(
            stage=GuardrailStage.INPUT,
            allowed=False,
            categories=categories,
            reason=f"Input matched a disallowed pattern ({', '.join(categories)}).",
        )

    # Stage 2: the real classifier is the actual gate.
    verdict = (classifier or _default_classifier()).classify(message)
    if verdict is None:
        # Classifier unavailable → fail open (see docstring). Deny-list already cleared it.
        return SafetyVerdict(stage=GuardrailStage.INPUT, allowed=True)
    if verdict.flagged:
        return SafetyVerdict(
            stage=GuardrailStage.INPUT,
            allowed=False,
            categories=[_PROMPT_INJECTION],
            reason=(
                f"Injection classifier flagged input as '{verdict.label}' "
                f"(score {verdict.score:.2f})."
            ),
        )
    return SafetyVerdict(stage=GuardrailStage.INPUT, allowed=True)


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


def screen_output(
    text: str, *, classifier: InjectionClassifier | None = None
) -> OutputScreenResult:
    """Redact injection echoes + system-prompt leakage from the final answer (§7 / §7.3 point 4).

    The P10-03 output guardrail. It runs up to three redaction stages over ``text`` and returns
    the (possibly scrubbed) answer; a redaction *neutralises* rather than *blocks* — the answer
    is still returned (``verdict.allowed`` stays ``True``), just cleaned.

    1. **Echoed-injection deny-list** — the same canonical jailbreak / prompt-injection phrasings
       :func:`screen_input` blocks on (reusing :data:`_DENY_PATTERNS` — one deny-list, both
       directions), matched anywhere in the answer and replaced with :data:`_OUTPUT_REDACTION`.
       Defends against the model echoing an instruction picked up from untrusted grounding
       material (a crawled page / CV saying "ignore previous instructions").
    2. **System-prompt leakage** — distinctive fixed scaffolding from the assistant's own
       instructions / the untrusted-content fence (:data:`_LEAKAGE_PATTERNS`) coaxed back into
       the answer, redacted the same way. Matched near-verbatim (case/whitespace tolerant).
    3. **Classifier net (opt-in)** — when ``classifier`` is supplied, each sentence/line of the
       answer is scored by the real P10-01 injection classifier and any flagged segment is
       redacted, so a *non-canonical* echoed instruction the deny-list misses is still caught.
       This is the same model that gates the input — one detection mechanism, not two. It is
       **opt-in** because it is a model call: the buffered
       :func:`app.agents.graph.output_guardrail_node` passes
       :func:`default_injection_classifier`; the per-chunk streaming path leaves it ``None`` (a
       per-delta model call would be prohibitively slow). Fail-soft: an unavailable classifier
       (``classify`` → ``None``) redacts nothing, mirroring :func:`screen_input`'s fail-open.

    Anything none of the stages recognise passes through unchanged (default-open). When nothing
    is redacted the returned ``text`` is byte-for-byte the input and ``modified`` is ``False``.
    """
    from app.agents.state import GuardrailStage, SafetyVerdict

    categories: list[str] = []
    scrubbed = text
    # Stages 1 + 2: one deterministic regex pass over both nets (same (pattern, category) shape).
    for pattern, category in (*_DENY_PATTERNS, *_LEAKAGE_PATTERNS):
        if pattern.search(scrubbed):
            scrubbed = pattern.sub(_OUTPUT_REDACTION, scrubbed)
            if category not in categories:
                categories.append(category)

    # Stage 3: opt-in classifier net over what the regex nets left (P10-01 reuse).
    if classifier is not None:
        scrubbed, flagged = _redact_flagged_segments(scrubbed, classifier)
        if flagged and _PROMPT_INJECTION not in categories:
            categories.append(_PROMPT_INJECTION)

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
            reason=f"Output screened and redacted ({', '.join(categories)}).",
        ),
        modified=True,
    )


def _redact_flagged_segments(text: str, classifier: InjectionClassifier) -> tuple[str, bool]:
    """Redact answer segments the injection classifier flags → ``(scrubbed, any_redacted)``.

    Splits ``text`` on sentence / line boundaries (delimiters preserved) and scores each
    letter-bearing segment with ``classifier``; a flagged segment — an injection instruction
    echoed from untrusted grounding the deny-list did not recognise — is replaced with
    :data:`_OUTPUT_REDACTION`. Fail-soft: a segment the classifier cannot score (``classify``
    returns ``None`` — model/library unavailable) is left untouched (default-open, mirroring
    :func:`screen_input`'s fail-open). Returns the text unchanged (byte-identical) when nothing
    is flagged, so a clean answer is never rewritten.
    """
    changed = False
    out: list[str] = []
    for segment in _OUTPUT_SEGMENT_SPLIT.split(text):
        if _has_letter(segment):
            verdict = classifier.classify(segment)
            if verdict is not None and verdict.flagged:
                out.append(_OUTPUT_REDACTION)
                changed = True
                continue
        out.append(segment)
    return ("".join(out), True) if changed else (text, False)


def _has_letter(segment: str) -> bool:
    """True if ``segment`` carries at least one letter (skips bare punctuation / whitespace)."""
    return any(char.isalpha() for char in segment)
