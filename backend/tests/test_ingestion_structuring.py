"""Unit tests for the LLM-assisted profile structuring step (P5-03, design §5.1).

Covers the acceptance criteria:

* a full CV Markdown → a correctly populated :class:`ProfileSchema`,
* a partial CV (missing sections) degrades gracefully into empty lists/fields — no error,
* the malformed-output paths (no tool call, non-JSON args, non-object args, schema-invalid
  payload, and an LLM error) all raise the single :class:`ProfileStructuringError`, and
* the structurer forces the ``record_profile`` tool call and feeds the LLM the CV Markdown.

The LLM boundary is always a :class:`FakeCompleter`; no test hits a real HF endpoint.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.ingestion.profile import ProfileSchema, ProfileStructuringError
from app.ingestion.structuring import (
    PROFILE_TOOL_NAME,
    PROFILE_TOOL_SCHEMA,
    ProfileStructurer,
    _parse_profile,
)
from app.ingestion.types import ParsedDocument
from app.llm.errors import LLMAllModelsFailedError
from app.llm.types import (
    ChatMessage,
    CompletionResult,
    FunctionCall,
    ToolCall,
    ToolSchema,
)


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeCompleter:
    """Programmable :class:`~app.ingestion.structuring.LLMCompleter` double.

    Returns ``result`` from :meth:`complete`, or raises ``error`` when set. Records the last
    call's ``messages`` / ``tools`` / ``tool_choice`` so tests can assert the structurer
    forced the tool call correctly.
    """

    def __init__(
        self,
        *,
        result: CompletionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls = 0
        self.last_messages: list[ChatMessage] = []
        self.last_tools: Sequence[ToolSchema] | None = None
        self.last_tool_choice: Any = None

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls += 1
        self.last_messages = list(messages)
        self.last_tools = tools
        self.last_tool_choice = tool_choice
        if self._error is not None:
            raise self._error
        assert self._result is not None, "FakeCompleter has no result"
        return self._result


def _tool_result(
    arguments: dict[str, Any] | str, *, name: str = PROFILE_TOOL_NAME
) -> CompletionResult:
    """A completion that forced-calls ``record_profile`` with ``arguments``."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(id="call_1", function=FunctionCall(name=name, arguments=raw))],
        finish_reason="tool_calls",
        model="fake",
    )


def _doc(markdown: str = "# CV", *, text: str | None = None) -> ParsedDocument:
    """A minimal :class:`ParsedDocument` carrying ``markdown`` (and optional plain text)."""
    return ParsedDocument(
        markdown=markdown,
        text=text if text is not None else markdown,
        source_format="docx",
    )


async def _structure(arguments: dict[str, Any] | str, *, doc: ParsedDocument | None = None) -> Any:
    """Run the structurer once against ``arguments`` and return the profile."""
    completer = FakeCompleter(result=_tool_result(arguments))
    return await ProfileStructurer(completer).structure(doc or _doc("# Jane Doe\nEngineer"))


# A synthetic but realistic fake-CV Markdown used by the full-extraction test.
_FAKE_CV_MARKDOWN = """
# Jane Doe

## Summary
Aspiring to lead a platform engineering team within three years.

## Skills
Python, PostgreSQL, Kubernetes, LangGraph

## Experience
### Senior Data Engineer — Acme Corp (2021 - Present)
Built the streaming ingestion platform and mentored three engineers.

### Data Engineer — Globex (2018 - 2021)
Owned the ETL pipelines feeding the analytics warehouse.

## Education
### MSc Computer Science — University of Edinburgh (2016 - 2018)
"""


# --------------------------------------------------------------------------- #
# Full extraction — a populated CV maps into a populated ProfileSchema
# --------------------------------------------------------------------------- #
async def test_full_cv_maps_into_populated_profile() -> None:
    args = {
        "skills": ["Python", "PostgreSQL", "Kubernetes", "LangGraph"],
        "experience": [
            {
                "title": "Senior Data Engineer",
                "company": "Acme Corp",
                "start_date": "2021",
                "end_date": "Present",
                "description": "Built the streaming ingestion platform.",
            },
            {
                "title": "Data Engineer",
                "company": "Globex",
                "start_date": "2018",
                "end_date": "2021",
                "description": "Owned the ETL pipelines.",
            },
        ],
        "education": [
            {
                "institution": "University of Edinburgh",
                "degree": "MSc",
                "field": "Computer Science",
                "start_date": "2016",
                "end_date": "2018",
            }
        ],
        "goals": ["Lead a platform engineering team within three years."],
    }
    profile = await _structure(args, doc=_doc(_FAKE_CV_MARKDOWN))

    assert isinstance(profile, ProfileSchema)
    assert profile.skills == ["Python", "PostgreSQL", "Kubernetes", "LangGraph"]
    assert [e.company for e in profile.experience] == ["Acme Corp", "Globex"]
    assert profile.experience[0].title == "Senior Data Engineer"
    assert profile.experience[0].end_date == "Present"
    assert profile.education[0].institution == "University of Edinburgh"
    assert profile.education[0].field == "Computer Science"
    assert profile.goals == ["Lead a platform engineering team within three years."]
    # round-trips to the JSONB document P5-04 will persist into profiles.data.
    assert profile.model_dump()["skills"] == args["skills"]


# --------------------------------------------------------------------------- #
# Graceful degradation — partial / missing sections yield empty fields, not errors
# --------------------------------------------------------------------------- #
async def test_missing_sections_default_to_empty() -> None:
    # A CV with only skills — no experience, education, or goals section.
    profile = await _structure({"skills": ["Excel"]})

    assert profile.skills == ["Excel"]
    assert profile.experience == []
    assert profile.education == []
    assert profile.goals == []


async def test_empty_arguments_yield_an_empty_profile() -> None:
    # The model called the tool but recorded nothing (a CV it could not parse into fields).
    profile = await _structure({})

    assert profile == ProfileSchema()


async def test_partial_experience_item_is_kept_not_dropped() -> None:
    # A role missing its title/dates still yields an entry (graceful degradation).
    profile = await _structure(
        {"experience": [{"company": "Acme Corp", "description": "Did things."}]}
    )

    assert len(profile.experience) == 1
    assert profile.experience[0].company == "Acme Corp"
    assert profile.experience[0].title is None
    assert profile.experience[0].start_date is None


async def test_empty_document_short_circuits_without_calling_llm() -> None:
    completer = FakeCompleter()  # no result set — must not be called.
    profile = await ProfileStructurer(completer).structure(
        ParsedDocument(markdown="   ", text="", source_format="pdf")
    )

    assert profile == ProfileSchema()
    assert completer.calls == 0


# --------------------------------------------------------------------------- #
# Error path — malformed output raises the single typed error
# --------------------------------------------------------------------------- #
async def test_no_tool_call_raises_structuring_error() -> None:
    completer = FakeCompleter(result=CompletionResult(content="free text", model="fake"))

    with pytest.raises(ProfileStructuringError):
        await ProfileStructurer(completer).structure(_doc())


async def test_malformed_json_arguments_raise_structuring_error() -> None:
    completer = FakeCompleter(result=_tool_result("{not valid json"))

    with pytest.raises(ProfileStructuringError):
        await ProfileStructurer(completer).structure(_doc())


async def test_non_object_arguments_raise_structuring_error() -> None:
    completer = FakeCompleter(result=_tool_result("[1, 2, 3]"))

    with pytest.raises(ProfileStructuringError):
        await ProfileStructurer(completer).structure(_doc())


async def test_schema_invalid_payload_raises_structuring_error() -> None:
    # skills must be a list of strings; a list of objects fails validation.
    completer = FakeCompleter(result=_tool_result({"skills": [{"name": "Python"}]}))

    with pytest.raises(ProfileStructuringError):
        await ProfileStructurer(completer).structure(_doc())


async def test_llm_error_is_wrapped_in_structuring_error() -> None:
    completer = FakeCompleter(error=LLMAllModelsFailedError("all down"))

    with pytest.raises(ProfileStructuringError):
        await ProfileStructurer(completer).structure(_doc())


def test_parse_profile_wraps_validation_error_as_cause() -> None:
    # the typed error preserves the underlying cause for debugging.
    with pytest.raises(ProfileStructuringError) as excinfo:
        _parse_profile(_tool_result({"skills": "not-a-list"}))

    assert excinfo.value.__cause__ is not None


# --------------------------------------------------------------------------- #
# Tool-call contract — the structurer forces record_profile and feeds it the CV
# --------------------------------------------------------------------------- #
async def test_structurer_forces_the_record_profile_tool() -> None:
    completer = FakeCompleter(result=_tool_result({"skills": ["Python"]}))

    await ProfileStructurer(completer).structure(_doc("# My CV\nPython developer"))

    assert completer.last_tools == [PROFILE_TOOL_SCHEMA]
    assert completer.last_tool_choice == {
        "type": "function",
        "function": {"name": PROFILE_TOOL_NAME},
    }
    assert completer.last_messages[0].role == "system"
    # the CV markdown is handed to the model as the user turn.
    assert "Python developer" in (completer.last_messages[-1].content or "")


async def test_structurer_prefers_markdown_over_plain_text() -> None:
    completer = FakeCompleter(result=_tool_result({}))
    await ProfileStructurer(completer).structure(
        ParsedDocument(markdown="# Rich CV", text="plain fallback", source_format="pdf")
    )

    joined = " ".join(m.content or "" for m in completer.last_messages)
    assert "Rich CV" in joined
    assert "plain fallback" not in joined


async def test_structurer_falls_back_to_plain_text_when_no_markdown() -> None:
    completer = FakeCompleter(result=_tool_result({}))
    await ProfileStructurer(completer).structure(
        ParsedDocument(markdown="", text="plain text CV body", source_format="pdf")
    )

    joined = " ".join(m.content or "" for m in completer.last_messages)
    assert "plain text CV body" in joined


def test_profile_tool_schema_matches_the_pydantic_model() -> None:
    # the tool schema is derived from ProfileSchema — single source of truth (no drift).
    params = PROFILE_TOOL_SCHEMA["function"]["parameters"]
    assert set(params["properties"]) == {"skills", "experience", "education", "goals"}
