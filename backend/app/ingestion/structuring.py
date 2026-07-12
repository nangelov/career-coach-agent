"""LLM-assisted structuring — ``ParsedDocument`` → :class:`ProfileSchema` (design §5.1).

This is the stage after layout-aware extraction: a :class:`~app.ingestion.types.ParsedDocument`
(layout-aware Markdown already recovered by docling/OCR in P5-01/P5-02) is handed to the LLM,
which maps it into the structured :class:`~app.ingestion.profile.ProfileSchema`
(skills / experience / education / goals). The result is the JSON document P5-04 persists into
``profiles.data`` (§4).

**Native tool-calling, no ReAct/regex parsing (locked decision, CLAUDE.md).** Exactly like the
planner (:mod:`app.agents.planner`), the structurer passes a single JSON-schema tool
(:data:`PROFILE_TOOL_SCHEMA`, derived from the Pydantic model so schema and validation never
drift) and forces the model to call it (``tool_choice`` pinned to that function). The structured
``ToolCall.function.arguments`` are validated straight into :class:`ProfileSchema`.

**Dependency (injected, mirrors the planner).** :class:`ProfileStructurer` takes an
:class:`LLMCompleter` — the structural shape of the P1-02 :class:`~app.llm.router.LLMRouter` /
P1-01 :class:`~app.llm.client.LLMClient` — by constructor injection, not a hand-rolled client, so
unit tests inject a fake (no HF calls) and production can point structuring at any model tier as a
wiring change. Kept as a structural :class:`~typing.Protocol` (not a hard import of ``LLMRouter``)
so ``ingestion`` depends on a *capability*, not on the ``llm`` concrete class.

**Failure contract (differs from the planner's fail-soft).** A *partial* CV degrades gracefully —
missing sections become empty lists/fields via the schema defaults, no error. But an
*unrecoverable* LLM failure (call raised, no tool call, non-JSON / non-object arguments, or a
payload that fails schema validation) raises a **single** :class:`ProfileStructuringError` so the
P5-04 Celery task can catch one error type. This stage does not silently return an empty profile on
malformed output — that would mask a broken parse as a valid-but-empty CV.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from app.ingestion.profile import ProfileSchema, ProfileStructuringError
from app.ingestion.types import ParsedDocument
from app.llm.errors import LLMError
from app.llm.types import ChatMessage, CompletionResult, ToolSchema

logger = logging.getLogger(__name__)

__all__ = [
    "LLMCompleter",
    "PROFILE_TOOL_NAME",
    "PROFILE_TOOL_SCHEMA",
    "ProfileStructurer",
]


@runtime_checkable
class LLMCompleter(Protocol):
    """The minimal LLM surface structuring needs: one buffered tool-call completion.

    Structural (not a hard import of :class:`~app.llm.router.LLMRouter`) so ``ingestion``
    depends on a capability: the real router / single-model client satisfy this shape, and
    tests inject a fake without touching HF. Mirrors :meth:`LLMRouter.complete` exactly.
    """

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = ...,
        tool_choice: str | dict[str, Any] | None = ...,
        temperature: float | None = ...,
        max_tokens: int | None = ...,
    ) -> CompletionResult: ...


#: The function the structurer forces the model to call (native tool-calling, no free text).
PROFILE_TOOL_NAME = "record_profile"


def _build_profile_tool_schema() -> ToolSchema:
    """Build the ``record_profile`` tool schema from :class:`ProfileSchema` itself.

    Deriving the ``parameters`` JSON schema from the Pydantic model (rather than
    hand-writing it, as the smaller planner schema does) keeps the tool contract and the
    validation model as a **single source of truth** — they cannot drift as fields change.
    """
    return {
        "type": "function",
        "function": {
            "name": PROFILE_TOOL_NAME,
            "description": (
                "Record the structured profile extracted from the candidate's CV: their "
                "skills, work experience, education, and any stated career goals. Leave a "
                "field empty when the CV does not mention it — do not invent information."
            ),
            "parameters": ProfileSchema.model_json_schema(),
        },
    }


#: The structurer's tool schema — same OpenAI ``tools[]`` shape as ``app/tools/`` (P1-03).
PROFILE_TOOL_SCHEMA: ToolSchema = _build_profile_tool_schema()

#: Forced tool choice: the model MUST call ``record_profile`` (no free-text escape hatch).
_FORCED_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": PROFILE_TOOL_NAME},
}

#: Focused extraction instruction — this is not the conversational system prompt.
STRUCTURING_SYSTEM_PROMPT = (
    "You are a CV/resume parser for a career-coaching assistant. Read the candidate's CV "
    "below (given as layout-aware Markdown) and call the record_profile function to record "
    "its structured content. Extract only what the CV actually states:\n"
    "- skills: distinct skills, tools and technologies mentioned.\n"
    "- experience: each role with its title, company, dates and a short description.\n"
    "- education: each qualification with institution, degree, field and dates.\n"
    "- goals: career goals or objectives if the CV states them (e.g. a summary/objective "
    "section); leave empty if none are stated.\n"
    "Leave any field empty when the CV does not mention it. Do not invent, infer beyond the "
    "text, or answer the candidate — only record what is written."
)

#: Cap on how much CV text is handed to the model. CVs are short (a few pages); this bounds a
#: pathological input (a huge merged PDF) without truncating any realistic CV.
_MAX_DOCUMENT_CHARS = 24_000


class ProfileStructurer:
    """LLM-assisted structuring step: :class:`ParsedDocument` → :class:`ProfileSchema`.

    Construct with an :class:`LLMCompleter` (normally the failover
    :class:`~app.llm.router.LLMRouter`) and call :meth:`structure`. Composable with the
    ingestion chain so P5-04 can run ``parser.parse() → structurer.structure()`` straight
    through.
    """

    def __init__(
        self,
        completer: LLMCompleter,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = 2048,
    ) -> None:
        """Bind the structurer to an LLM completer.

        Args:
            completer: The LLM surface to structure with — normally the failover
                :class:`~app.llm.router.LLMRouter`. Injected (not constructed) so pointing
                structuring at a different model tier is a wiring change later.
            temperature: Sampling temperature; ``0.0`` for stable, near-deterministic
                extraction.
            max_tokens: Generation cap for the (potentially large) tool-call response.
        """
        self._completer = completer
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def structure(self, document: ParsedDocument) -> ProfileSchema:
        """Map a parsed CV into a validated :class:`ProfileSchema`.

        Prefers the layout-aware :attr:`~app.ingestion.types.ParsedDocument.markdown` (the
        form the design earmarks for this step), falling back to plain
        :attr:`~app.ingestion.types.ParsedDocument.text`. An empty document short-circuits to
        an empty profile — there is nothing to extract, and that is a valid (if empty)
        result, not a failure.

        Raises:
            ProfileStructuringError: The LLM call failed, returned no usable ``record_profile``
                tool call, or returned a payload that does not match :class:`ProfileSchema`.
        """
        content = (document.markdown or "").strip() or (document.text or "").strip()
        if not content:
            # Nothing to parse (e.g. an image-only doc that recovered no text). An empty
            # profile is the graceful result, not an error.
            return ProfileSchema()

        messages = self._build_messages(content[:_MAX_DOCUMENT_CHARS])
        try:
            result = await self._completer.complete(
                messages,
                tools=[PROFILE_TOOL_SCHEMA],
                tool_choice=_FORCED_TOOL_CHOICE,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except LLMError as exc:
            logger.warning("profile structuring LLM call failed", exc_info=True)
            raise ProfileStructuringError("LLM call failed during profile structuring") from exc

        return _parse_profile(result)

    @staticmethod
    def _build_messages(content: str) -> list[ChatMessage]:
        """Assemble the structuring prompt: instruction + the CV Markdown as the user turn."""
        return [
            ChatMessage(role="system", content=STRUCTURING_SYSTEM_PROMPT),
            ChatMessage(role="user", content=f"CV to parse:\n\n{content}"),
        ]


def _parse_profile(result: CompletionResult) -> ProfileSchema:
    """Validate the forced ``record_profile`` tool call into a :class:`ProfileSchema`.

    Raises :class:`ProfileStructuringError` on any unrecoverable shape problem (no tool call,
    non-JSON / non-object arguments, or a schema-validation failure). A merely *partial*
    payload — missing sections — validates fine via the schema's empty defaults.
    """
    if not result.tool_calls:
        raise ProfileStructuringError("model returned no record_profile tool call")

    raw = result.tool_calls[0].function.arguments
    try:
        args = json.loads(raw) if raw and raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise ProfileStructuringError("record_profile arguments were not valid JSON") from exc
    if not isinstance(args, dict):
        raise ProfileStructuringError("record_profile arguments were not a JSON object")

    try:
        return ProfileSchema.model_validate(args)
    except ValidationError as exc:
        raise ProfileStructuringError("structured profile failed schema validation") from exc
