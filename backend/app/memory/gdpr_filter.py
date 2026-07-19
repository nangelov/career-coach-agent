"""GDPR Art. 9 special-category detection for the teachable-memory learn loop (§7.6).

A career coach *will* receive special-category data — "I'm returning after cancer
treatment", "I have ADHD, what roles suit me?", "I can't work Fridays for religious
reasons". These are legitimate, in-turn context, but under **GDPR Art. 9** they must
**never become durable learned memories**. This module is the deterministic gate the
P9-04 learn step runs over every candidate memory's text *before* it is persisted: a
candidate that trips the filter is **dropped** (used within the turn only, never
written to ``user_memories``).

**Design posture (read before extending).** This mirrors the *minimal deterministic
slice* posture of :mod:`app.llm.redaction` and :mod:`app.guardrails.heuristics`:
compiled keyword/regex lists per category, **no ML/NER dependency**, no network, no
I/O — cheap and unit-testable in isolation, consistent with the OSS/free budget. A real
special-category classifier is a later, dedicated investment (same tier as the P10
injection classifier); this is the coarse net for now.

**Direction of error is deliberately "drop".** Unlike the input guardrail (default-open
to avoid blocking legitimate questions), this filter's *failure* mode is to **over-drop**:
a false positive only means a benign memory is not made durable (no data loss the user
notices — the turn's own response is unaffected), whereas a false negative persists a
special category. So the category lists lean slightly broad, and we accept that some
benign candidates will be conservatively withheld from durable storage.

**Honest limitations (best-effort by category).** Keyword/phrase matching only — it
catches the direct, unobfuscated mentions a coaching conversation actually produces
("I have depression", "I'm on medical leave", "as a practising Muslim"). It will miss
euphemism, heavy paraphrase, or non-English phrasing, and can occasionally over-match a
word used in a non-special sense (e.g. "union" contexts are therefore matched only via
multi-word union-membership phrasings, not the bare word). This is coarse-by-design.

Covered Art. 9 categories: **health**, **disability**, **ethnicity/race**, **religion**,
**trade-union membership**, **sexual orientation / sexuality**. (Political opinions and
biometric/genetic data are the remaining Art. 9 categories; a career coach is far less
likely to elicit them and they are out of scope for this coarse slice — extend here if
that changes.)
"""

from __future__ import annotations

import re

__all__ = ["SpecialCategory", "contains_special_category", "special_category_of"]

#: Human-readable Art. 9 category labels (internal telemetry / logging only — never
#: surfaced to the user; matching one just means "do not persist").
SpecialCategory = str

_HEALTH = "health"
_DISABILITY = "disability"
_ETHNICITY = "ethnicity"
_RELIGION = "religion"
_UNION = "trade_union"
_SEXUALITY = "sexuality"


def _words(*terms: str) -> re.Pattern[str]:
    """Compile an alternation of ``terms`` as case-insensitive whole-word matches.

    Each term may itself contain ``\\s+`` etc.; ``\\b`` anchors keep e.g. "ill" from
    matching inside "skill" or "union" inside "reunion".
    """
    joined = "|".join(terms)
    return re.compile(rf"\b(?:{joined})\b", re.IGNORECASE)


# Per category: a compiled pattern of the direct mentions a coaching turn realistically
# yields. Lists are deliberately specific enough to avoid the most common benign
# career-text collisions (see the union note above) while erring toward "drop".
_CATEGORY_PATTERNS: tuple[tuple[SpecialCategory, re.Pattern[str]], ...] = (
    (
        _HEALTH,
        _words(
            r"health\s+condition",
            r"mental\s+health",
            "illness",
            "diagnosis",
            "diagnosed",
            "disease",
            "cancer",
            "chemotherapy",
            "chemo",
            "depression",
            "depressed",
            "anxiety",
            "bipolar",
            "schizophreni\\w*",
            "ptsd",
            "diabetes",
            "diabetic",
            "epilepsy",
            "hiv",
            "chronic\\s+\\w+",
            "medication",
            "medicated",
            r"medical\s+leave",
            r"sick\s+leave",
            "hospitalised",
            "hospitalized",
            "surgery",
            "therapy",
            "therapist",
            "psychiatric",
            "psychiatrist",
            "pregnant",
            "pregnancy",
            "burnout",
            "burned\\s+out",
            "burnt\\s+out",
        ),
    ),
    (
        _DISABILITY,
        _words(
            "disabled",
            "disability",
            "disabilities",
            "impairment",
            "wheelchair",
            "blind",
            "visually\\s+impaired",
            "deaf",
            "hard\\s+of\\s+hearing",
            "neurodivergent",
            "neurodiverse",
            "adhd",
            "autism",
            "autistic",
            "dyslexia",
            "dyslexic",
            "dyspraxia",
            "chronic\\s+illness",
            "chronically\\s+ill",
        ),
    ),
    (
        _ETHNICITY,
        _words(
            "ethnicity",
            "ethnic\\s+background",
            "ethnic\\s+minority",
            "racial",
            "mixed\\s+race",
            "person\\s+of\\s+colou?r",
            "people\\s+of\\s+colou?r",
            "hispanic",
            "latino",
            "latina",
            "latinx",
            "indigenous",
            "caucasian",
            "african[\\s\\-]american",
            "afro[\\s\\-]\\w+",
        ),
    ),
    (
        _RELIGION,
        _words(
            "religion",
            "religious",
            "faith\\s+background",
            "christian",
            "catholic",
            "protestant",
            "muslim",
            "islam",
            "islamic",
            "jewish",
            "judaism",
            "hindu",
            "hinduism",
            "buddhist",
            "buddhism",
            "sikh",
            "atheist",
            "agnostic",
            "practising",
            "practicing",  # "practising/practicing Muslim/Catholic/…"
            "church",
            "mosque",
            "synagogue",
            "temple",
            "ramadan",
            "sabbath",
        ),
    ),
    (
        _UNION,
        # Bare "union" collides with "European Union"; require a membership phrasing.
        _words(
            "trade\\s+union",
            "labou?r\\s+union",
            "union\\s+member",
            "union\\s+membership",
            "unionised",
            "unionized",
            "union\\s+rep(?:resentative)?",
            "shop\\s+steward",
            "collective\\s+bargaining",
        ),
    ),
    (
        _SEXUALITY,
        _words(
            "sexual\\s+orientation",
            "sexuality",
            "gay",
            "lesbian",
            "bisexual",
            "homosexual",
            "heterosexual",
            "queer",
            "lgbt\\w*",
            "transgender",
            "non[\\s\\-]binary",
            "same[\\s\\-]sex",
            "coming\\s+out",
        ),
    ),
)


def special_category_of(text: str) -> SpecialCategory | None:
    """Return the first GDPR Art. 9 category ``text`` trips, or ``None`` if it is clean.

    Deterministic, no I/O. Intended to run on a candidate memory's text *after* contact
    redaction (see :mod:`app.memory.learn`) — the redaction markers it inserts
    (``[EMAIL REDACTED]`` etc.) contain no special-category terms, so the two do not
    interfere. Returns the category label for logging/telemetry; callers that only need
    a yes/no use :func:`contains_special_category`.
    """
    if not text:
        return None
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return None


def contains_special_category(text: str) -> bool:
    """``True`` if ``text`` mentions any covered GDPR Art. 9 special category (see module)."""
    return special_category_of(text) is not None
