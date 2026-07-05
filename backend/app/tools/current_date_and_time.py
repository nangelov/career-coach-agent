"""`current_date_and_time` — the trivial, dependency-free reference tool.

This is the "prove the plumbing works" tool (task P1-03): no external I/O, so it
demonstrates the schema + async-executor + registry pattern in isolation. It
returns the current date/time, optionally in a caller-supplied IANA timezone.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import Tool, ToolResult, ToolSchema

_SCHEMA: ToolSchema = {
    "type": "function",
    "function": {
        "name": "current_date_and_time",
        "description": (
            "Return the current date and time. Optionally specify an IANA timezone "
            "name to get the local time there; defaults to UTC."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone name, e.g. 'Europe/Sofia' or 'America/New_York'. "
                        "Defaults to 'UTC' when omitted."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


class CurrentDateTimeTool(Tool):
    """Return the current date/time, optionally in a given IANA timezone."""

    @property
    def name(self) -> str:
        return "current_date_and_time"

    @property
    def schema(self) -> ToolSchema:
        return _SCHEMA

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        tz_name = arguments.get("timezone", "UTC")
        if not isinstance(tz_name, str) or not tz_name.strip():
            tz_name = "UTC"
        try:
            tzinfo = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            return ToolResult.error(f"Unknown timezone: {tz_name!r}.")

        now = datetime.now(tzinfo)
        return ToolResult.ok(
            {
                "timezone": tz_name,
                "iso8601": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "weekday": now.strftime("%A"),
                "unix": int(now.timestamp()),
            }
        )
