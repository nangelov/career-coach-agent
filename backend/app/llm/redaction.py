"""Contact-detail redaction at the LLM egress boundary (design §6.16 / §7.6).

CV data is the most PII-dense document a user owns, and on every RAG-grounded turn
some of it (the CV-structuring input, or the user's own embedded ``kb_chunks``
re-entering the responder's grounding block) is sent to a **third-party inference
provider**. Before any external model call we strip the **directly-identifying**
contact fields — **name, email, phone, postal address, personal URLs/profile
links** — while **keeping** the substance the coach actually reasons about:
employers, titles, dates, skills, education.

Redaction lives at **one chokepoint** — :class:`~app.llm.router.LLMRouter` calls
:func:`redact_messages` on outbound content before any underlying ``client``
call — rather than being scattered across every agent that builds a prompt. See
the router for the wiring; this module is pure, deterministic text transformation
with no I/O.

**Design posture (read before extending).** This is the same *minimal deterministic
slice* posture as the P4 input guardrails (:mod:`app.guardrails.heuristics`): coarse
regex/heuristics, **not** a full NER/ML PII detector, consistent with the OSS/free
budget. Compiled regexes only, no network, no ML dependency — cheap enough to run on
every LLM call including the hot chat path.

**Honest limitations (best-effort by category).**

* **Email** — reliable regex; high coverage.
* **Personal URLs / profile links** — ``http(s)://…``, ``www.…``, and bare
  ``linkedin.com/github.com`` links are stripped. We do **not** try to distinguish a
  "personal" link from a "professional" one — *all* URLs in outbound content are
  redacted. This over-redacts benign links, which is the safe direction at an egress
  boundary.
* **Phone** — covers ``+``-prefixed international numbers, ``(area) 000-0000``, and
  ``000-000-0000``-style US numbers (grouping with two separators / a leading ``+``).
  Deliberately conservative: a single-separator run like a ``2019-2023`` date range is
  **not** treated as a phone number. Loose/label-free formats may slip through.
* **Postal address** — best-effort and **partial**: a ``<number> <street> <suffix>``
  line and a ``City, ST 00000`` line. Free-form or non-US addresses will often be
  missed. Not reliable — documented as such.
* **Name** — hardest without real NER. Best-effort only: an explicit ``Name:``-labelled
  line, and a bare "Firstname Lastname" résumé-header line **when it is the first
  non-empty line** of the content. This can both miss real names and (rarely) catch a
  capitalized non-name first line. Not guaranteed.
* **Photo / images** — **N/A here.** No current path sends raw image bytes to the chat
  LLM (the P5 VLM-OCR path is only *reserved*, not implemented), so a text-only
  chokepoint has nothing to redact. Accepted current-state limitation, not a gap.

Non-goals: this does **not** touch the embedding pipeline
(:mod:`app.llm.embeddings`) — that concerns stored vectors, not the external-inference
egress path — nor does it redact model-generated ``tool_calls`` arguments (structured
model output, out of scope for this boundary).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .types import ChatMessage

__all__ = ["redact_contact_details", "redact_messages"]

# --- replacement markers ---------------------------------------------------- #
# Visible, neutral markers (mirroring guardrails' ``[removed]`` convention) so a
# redaction is auditable and the surrounding text stays readable to the model.
_EMAIL_MARK = "[EMAIL REDACTED]"
_PHONE_MARK = "[PHONE REDACTED]"
_URL_MARK = "[URL REDACTED]"
_ADDRESS_MARK = "[ADDRESS REDACTED]"
_NAME_MARK = "[NAME REDACTED]"

# --- email ------------------------------------------------------------------ #
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)

# --- personal URLs / profile links ------------------------------------------ #
# Full URLs, bare ``www.`` hosts, and scheme-less linkedin/github profile links.
_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\)\]]+"
    r"|(?:linkedin\.com|github\.com)/[^\s<>\)\]]+",
    re.IGNORECASE,
)

# --- phone numbers ---------------------------------------------------------- #
# Conservative: a ``+``-prefixed international number, a US ``(area) 000-0000`` /
# ``000-000-0000`` grouping (two separators). A single-separator run such as the
# date range ``2019-2023`` is intentionally NOT matched.
_PHONE = re.compile(
    r"""
    (?<![\w+])                                        # not mid-token / not part of +NN
    (?:
        \+\d{1,3}[\s.\-]?(?:\(\d{1,4}\)[\s.\-]?)?      # +CC, optional (area)
            \d{1,4}(?:[\s.\-]?\d{2,4}){1,}             #   grouped digits
      | \(\d{3}\)[\s.\-]?\d{3}[\s.\-]?\d{4}            # (123) 456-7890
      | \d{3}[\s.\-]\d{3}[\s.\-]\d{4}                  # 123-456-7890 (two separators)
    )
    (?!\w)
    """,
    re.VERBOSE,
)

# --- postal address (best-effort, partial) ---------------------------------- #
_STREET_SUFFIX = (
    r"Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|"
    r"Way|Place|Pl|Terrace|Ter|Circle|Cir|Highway|Hwy|Square|Sq"
)
_ADDRESS = re.compile(
    # "123 Main Street" / "45 Elm Ave" — number + 1-4 capitalised words + suffix.
    rf"\b\d{{1,6}}\s+(?:[A-Z][A-Za-z.]*\s+){{1,4}}(?:{_STREET_SUFFIX})\b\.?"
    # "Springfield, IL 62704" — city, 2-letter state, US ZIP(+4).
    r"|\b[A-Z][A-Za-z.\-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b",
)

# --- name (best-effort) ----------------------------------------------------- #
# An explicit ``Name:`` line, anywhere in the content.
_NAME_LABELLED = re.compile(
    r"(?im)^([ \t]*name[ \t]*[:\-][ \t]*).+$",
)
# A bare "Firstname Lastname" (2-3 capitalised words) résumé header — only honoured
# when it is the FIRST non-empty line (see :func:`_redact_header_name`).
_NAME_HEADER = re.compile(
    r"^[A-Z][a-z'\-]+(?:[ \t]+[A-Z][a-z'\-]+){1,2}$",
)


def _redact_header_name(text: str) -> str:
    """Strip a bare "Firstname Lastname" line iff it is the first non-empty line.

    Best-effort résumé-header heuristic: CVs commonly open with the candidate's name
    on its own line. Scoped to the first non-empty line to avoid mangling ordinary
    prose further down.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if _NAME_HEADER.match(line.strip()):
            lines[i] = _NAME_MARK
        break  # only inspect the first non-empty line
    return "\n".join(lines)


def redact_contact_details(text: str) -> str:
    """Redact directly-identifying contact details from ``text`` (design §6.16).

    Applies the email / URL / phone / address / name heuristics documented in the
    module docstring, replacing each match with a neutral ``[… REDACTED]`` marker.
    Ordinary CV substance — employers, titles, dates, skills, education — is left
    untouched. Best-effort and deterministic; see the module docstring for the
    coverage limits of each category.
    """
    if not text:
        return text
    # Order matters: emails before URLs (an email is not a URL but both touch dots),
    # then structural patterns, then the label/header name heuristics last.
    text = _EMAIL.sub(_EMAIL_MARK, text)
    text = _URL.sub(_URL_MARK, text)
    text = _PHONE.sub(_PHONE_MARK, text)
    text = _ADDRESS.sub(_ADDRESS_MARK, text)
    text = _NAME_LABELLED.sub(rf"\1{_NAME_MARK}", text)
    text = _redact_header_name(text)
    return text


def redact_messages(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    """Return a copy of ``messages`` with contact details redacted from content.

    Only the textual ``content`` of each message is redacted; message metadata and
    model-generated ``tool_calls`` are left intact (out of scope for this boundary).
    Messages whose content is unchanged (or ``None``) are returned as-is to avoid
    needless copies on the hot chat path.
    """
    redacted: list[ChatMessage] = []
    for message in messages:
        if not message.content:
            redacted.append(message)
            continue
        cleaned = redact_contact_details(message.content)
        if cleaned == message.content:
            redacted.append(message)
        else:
            redacted.append(message.model_copy(update={"content": cleaned}))
    return redacted
