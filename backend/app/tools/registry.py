"""Default tool-registry factory — the one place tools are wired together.

Adding a new tool (P4+) is: implement a :class:`~app.tools.base.Tool`, import it
here, and ``register`` it. Nothing else in the app needs to change — callers ask
the registry for :meth:`~app.tools.base.ToolRegistry.schemas` (to pass to the LLM)
and :meth:`~app.tools.base.ToolRegistry.execute` (to run a model's tool call).
"""

from __future__ import annotations

import httpx

from app.config import Settings, settings

from .base import ToolRegistry
from .current_date_and_time import CurrentDateTimeTool
from .internet_search import InternetSearchTool


def build_default_registry(
    config: Settings = settings,
    *,
    search_http_client: httpx.AsyncClient | None = None,
) -> ToolRegistry:
    """Build the app's default tool registry.

    Args:
        config: Application settings (for the search backend URL / timeout).
        search_http_client: Optional injected ``httpx.AsyncClient`` for
            ``internet_search`` (tests supply a mock-transport client).
    """
    registry = ToolRegistry()
    registry.register(CurrentDateTimeTool())
    registry.register(InternetSearchTool.from_settings(config, http_client=search_http_client))
    return registry
