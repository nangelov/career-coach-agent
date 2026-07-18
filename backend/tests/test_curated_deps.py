"""Tests for the curated-dependency drift guard (scripts/check_curated_deps.py).

Covers the positive case (the real repo files are currently clean) and several
negative cases (a simulated uncurated dep / list drift / stale allowlist entry
each fails with a clear, package-named message).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_SCRIPT_PATH = _BACKEND_DIR / "scripts" / "check_curated_deps.py"

_spec = importlib.util.spec_from_file_location("check_curated_deps", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


# --- Positive case: the real, committed files are clean --------------------


def test_real_repo_files_are_clean() -> None:
    """Today's curated lists cover every runtime dep — no drift right now."""
    problems = guard.run_check(_BACKEND_DIR, _REPO_ROOT)
    assert problems == [], "\n".join(problems)


# --- Parsing helpers -------------------------------------------------------


def test_normalize_strips_extras_version_and_quotes() -> None:
    assert guard.normalize('"celery[redis]>=5.3.0"') == "celery"
    assert guard.normalize("uvicorn[standard]>=0.27.0") == "uvicorn"
    assert guard.normalize("google_search_results>=2.4.0") == "google-search-results"


def test_curated_from_text_parses_yaml_run_block() -> None:
    text = (
        "      - name: Install dependencies\n"
        "        run: |\n"
        "          uv sync --only-group dev\n"
        "          uv pip install fastapi pydantic \\\n"
        '            "celery[redis]" reportlab\n'
    )
    assert guard.curated_from_text(text) == {"fastapi", "pydantic", "celery", "reportlab"}


def test_curated_from_text_parses_makefile_recipe() -> None:
    text = "install:\n\tuv sync --only-group dev\n\tuv pip install fastapi asyncpg\n"
    assert guard.curated_from_text(text) == {"fastapi", "asyncpg"}


# --- Negative cases (synthetic inputs) -------------------------------------

_ALLOWLIST = {"torch": "heavy ML"}


def test_uncurated_runtime_dep_fails_by_name() -> None:
    problems = guard.find_problems(
        runtime={"fastapi", "newlib", "torch"},
        dev=set(),
        curated_ci={"fastapi"},
        curated_make={"fastapi"},
        allowlist=_ALLOWLIST,
    )
    assert len(problems) == 1
    assert "'newlib'" in problems[0]
    assert "backend-ci.yml" in problems[0] and "Makefile" in problems[0]


def test_allowlisted_dep_is_not_flagged() -> None:
    problems = guard.find_problems(
        runtime={"fastapi", "torch"},
        dev=set(),
        curated_ci={"fastapi"},
        curated_make={"fastapi"},
        allowlist=_ALLOWLIST,
    )
    assert problems == []


def test_dev_group_dep_is_not_flagged() -> None:
    problems = guard.find_problems(
        runtime={"fastapi", "httpx", "torch"},
        dev={"httpx"},
        curated_ci={"fastapi"},
        curated_make={"fastapi"},
        allowlist=_ALLOWLIST,
    )
    assert problems == []


def test_drift_between_ci_and_makefile_fails() -> None:
    problems = guard.find_problems(
        runtime={"fastapi", "asyncpg"},
        dev=set(),
        curated_ci={"fastapi", "asyncpg"},
        curated_make={"fastapi"},
        allowlist=_ALLOWLIST,
    )
    assert any("drifted" in p and "asyncpg" in p for p in problems)


def test_stale_allowlist_entry_fails() -> None:
    problems = guard.find_problems(
        runtime={"fastapi"},
        dev=set(),
        curated_ci={"fastapi"},
        curated_make={"fastapi"},
        allowlist={"torch": "heavy ML"},
    )
    assert any("no longer a declared" in p and "'torch'" in p for p in problems)
