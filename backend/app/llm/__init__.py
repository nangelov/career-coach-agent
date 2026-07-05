"""LLM layer — provider-agnostic client interface, types, and errors.

``client.py`` holds the ``LLMClient`` interface + the HF OpenAI-compatible
implementation (P1-01).  ``router.py`` (P1-02) adds the failover router over an
ordered list of clients.  The in-process embeddings client (``embeddings.py``)
lands in a later task.
"""

from .client import HFOpenAICompatibleClient, LLMClient, ToolSchema
from .errors import (
    LLMAllModelsFailedError,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from .router import CircuitBreaker, LLMRouter, RedisLike
from .types import (
    ChatMessage,
    CompletionResult,
    FunctionCall,
    Role,
    StreamChunk,
    ToolCall,
    ToolCallDelta,
)

__all__ = [
    "ChatMessage",
    "CircuitBreaker",
    "CompletionResult",
    "FunctionCall",
    "HFOpenAICompatibleClient",
    "LLMAllModelsFailedError",
    "LLMClient",
    "LLMConnectionError",
    "LLMError",
    "LLMRateLimitError",
    "LLMResponseError",
    "LLMRouter",
    "LLMTimeoutError",
    "RedisLike",
    "Role",
    "StreamChunk",
    "ToolCall",
    "ToolCallDelta",
    "ToolSchema",
]
