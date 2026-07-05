"""Native tool-call definitions: JSON schemas + async executors + registry.

Public surface:

* :class:`Tool` / :class:`ToolResult` / :class:`ToolRegistry` — the pattern.
* :data:`ToolSchema` — the OpenAI ``tools[]`` dict shape.
* :class:`CurrentDateTimeTool`, :class:`InternetSearchTool` — the P1-03 tools.
* :func:`build_default_registry` — the single wiring point.
"""

from __future__ import annotations

from .base import Tool, ToolRegistry, ToolResult, ToolSchema
from .current_date_and_time import CurrentDateTimeTool
from .internet_search import InternetSearchTool
from .registry import build_default_registry

__all__ = [
    "CurrentDateTimeTool",
    "InternetSearchTool",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "ToolSchema",
    "build_default_registry",
]
