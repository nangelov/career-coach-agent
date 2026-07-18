"""Unit tests for the PDP → dashboard line-item parser (P8-04, §5.2).

Covers :func:`~app.services.pdp_seed.parse_line_items` in isolation: bullet and numbered lists,
markdown stripping, checkboxes, prose/heading skipping, de-duplication, length capping, and the
degrade-to-empty case. The service-level seeding flow (goal reuse/de-dup, fail-soft) is exercised in
``tests/test_pdp_service.py``.
"""

from __future__ import annotations

from app.services.pdp_seed import _MAX_ITEMS_PER_SECTION, _TITLE_MAX_LEN, parse_line_items


def test_dash_and_star_bullets_are_extracted() -> None:
    text = "- Learn SQL\n* Build a pipeline\n• Ship a project"
    assert parse_line_items(text) == ["Learn SQL", "Build a pipeline", "Ship a project"]


def test_numbered_lists_dot_and_paren() -> None:
    text = "1. First step\n2) Second step\n10. Tenth step"
    assert parse_line_items(text) == ["First step", "Second step", "Tenth step"]


def test_markdown_emphasis_and_code_are_stripped() -> None:
    text = "- **Learn SQL fundamentals**\n- *Refactor* the `ingest` module"
    assert parse_line_items(text) == ["Learn SQL fundamentals", "Refactor the ingest module"]


def test_leading_checkbox_is_stripped() -> None:
    text = "- [ ] Enrol in a course\n- [x] Finish the intro"
    assert parse_line_items(text) == ["Enrol in a course", "Finish the intro"]


def test_prose_and_headings_are_skipped() -> None:
    text = "Here is my plan for the quarter.\n\n## Objectives\n\nSome intro prose with no bullets."
    assert parse_line_items(text) == []


def test_empty_and_whitespace_yield_nothing() -> None:
    assert parse_line_items("") == []
    assert parse_line_items("   \n\n  \t ") == []


def test_intro_line_then_bullets_keeps_only_bullets() -> None:
    text = "Milestones:\n- Learn SQL\n- Build a pipeline"
    assert parse_line_items(text) == ["Learn SQL", "Build a pipeline"]


def test_case_insensitive_duplicates_are_dropped() -> None:
    text = "- Learn SQL\n- learn sql\n- Learn SQL"
    assert parse_line_items(text) == ["Learn SQL"]


def test_blank_bullet_is_skipped() -> None:
    # A marker with only markdown/whitespace after it collapses to empty → not seeded.
    text = "- **  **\n- Real item"
    assert parse_line_items(text) == ["Real item"]


def test_items_are_truncated_to_title_cap() -> None:
    long = "x" * (_TITLE_MAX_LEN + 50)
    (item,) = parse_line_items(f"- {long}")
    assert len(item) == _TITLE_MAX_LEN


def test_items_are_capped_per_section() -> None:
    text = "\n".join(f"- item {i}" for i in range(_MAX_ITEMS_PER_SECTION + 10))
    assert len(parse_line_items(text)) == _MAX_ITEMS_PER_SECTION
