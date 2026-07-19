"""Regression guard: no arbitrary-code-execution surface (P10-04, design §7).

v1 shipped a ``run_python_code`` REPL tool; v2 **removes** it (arbitrary-code-execution
risk — CLAUDE.md, design §7 "Tool isolation"). v2's tools were rebuilt from scratch and
none exposes code execution. These tests lock that in so a future PR cannot silently
reintroduce a REPL/eval tool:

1. Every LLM-callable tool the app registers (the default chat registry **and** the
   per-turn dashboard bundle) is checked — by exact known-good name set and against a
   code-exec denylist on name + description.
2. The whole ``backend/app`` tree is scanned for code-execution builtins (``exec(``,
   ``eval(``, ``subprocess``, ``__import__``, ``PythonREPL`` …) — a REPL tool cannot be
   built without one of these, so their absence is the durable guarantee.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import app
from app.services.dashboard import DashboardService
from app.tools import build_default_registry
from app.tools.dashboard import build_dashboard_tools

# The complete set of tool names the app can register (default chat registry +
# per-turn dashboard bundle). Assert-exactly so *any* new tool forces a conscious
# update here — the point where a reintroduced REPL would have to be noticed.
_KNOWN_GOOD_TOOL_NAMES = frozenset(
    {
        "current_date_and_time",
        "internet_search",
        "read_dashboard",
        "propose_goal",
        "propose_milestone",
        "propose_task",
        "log_progress",
    }
)

# Substrings that betray a code-execution tool by name.
_CODE_EXEC_NAME_TOKENS = (
    "python",
    "repl",
    "exec",
    "eval",
    "shell",
    "bash",
    "subprocess",
    "run_code",
    "code_interpreter",
    "interpreter",
)

# Phrases that betray a code-execution tool by description.
_CODE_EXEC_DESC_PATTERNS = (
    re.compile(r"execute\s+(?:python|code|a\s+script|commands?)", re.IGNORECASE),
    re.compile(r"run\s+(?:python|arbitrary|shell)\b", re.IGNORECASE),
    re.compile(r"code\s+interpreter", re.IGNORECASE),
    re.compile(r"\brepl\b", re.IGNORECASE),
)

# Code-execution builtins/imports. A REPL tool cannot exist without one of these, so
# scanning source is a stronger guard than any name check. ``re.compile`` / method
# ``.compile()`` / ``.execute()`` are legitimate and deliberately excluded by the
# word-boundary + literal-paren patterns below.
_CODE_EXEC_SOURCE_PATTERNS = (
    re.compile(r"\bexec\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bos\.system\b"),
    re.compile(r"\bos\.popen\b"),
    re.compile(r"\b__import__\s*\("),
    re.compile(r"\bpty\.spawn\b"),
    re.compile(r"PythonREPL|python_repl|run_python"),
)


def _all_registered_tools() -> list[tuple[str, str]]:
    """Return ``(name, description)`` for every tool the app can register."""
    schemas = list(build_default_registry().schemas())
    # The dashboard bundle is built per-turn; a dummy service is fine — we only read
    # schema/name, never call the service.
    dummy_service = cast("DashboardService", object())
    schemas += [t.schema for t in build_dashboard_tools("user-1", dummy_service)]
    return [(s["function"]["name"], s["function"]["description"]) for s in schemas]


def test_registered_tool_set_is_exactly_the_known_good_set() -> None:
    names = {name for name, _ in _all_registered_tools()}
    assert names == set(_KNOWN_GOOD_TOOL_NAMES), (
        "Registered tool set changed — if you added a tool, confirm it is NOT a "
        "code-execution/REPL tool (design §7) and update _KNOWN_GOOD_TOOL_NAMES."
    )


def test_no_registered_tool_exposes_code_execution() -> None:
    for name, description in _all_registered_tools():
        lowered = name.lower()
        assert not any(token in lowered for token in _CODE_EXEC_NAME_TOKENS), (
            f"Tool {name!r} looks like a code-execution tool (design §7 forbids it)."
        )
        assert not any(pat.search(description) for pat in _CODE_EXEC_DESC_PATTERNS), (
            f"Tool {name!r} description advertises code execution (design §7 forbids it)."
        )


def test_no_code_execution_surface_in_backend_app() -> None:
    app_root = Path(app.__file__).resolve().parent
    offenders: list[str] = []
    for source in app_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        for pattern in _CODE_EXEC_SOURCE_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{source.relative_to(app_root)}: {pattern.pattern}")
    assert not offenders, (
        "Code-execution surface found in backend/app (design §7: v1 run_python_code "
        "REPL is removed, no exec/eval/subprocess/REPL). Offenders: " + "; ".join(offenders)
    )
