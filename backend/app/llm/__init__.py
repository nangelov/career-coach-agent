"""LLM layer — provider-agnostic client interface, types, and errors.

``client.py`` holds the ``LLMClient`` interface + the HF OpenAI-compatible
implementation (P1-01).  ``router.py`` (P1-02) adds the failover router over an
ordered list of clients.  ``embeddings.py`` (P2-06) holds the in-process
``EmbeddingClient`` interface + its ``sentence-transformers`` implementation.
"""

from .client import HFOpenAICompatibleClient, LLMClient, ToolSchema
from .embeddings import (
    DEFAULT_QUERY_TASK,
    EmbeddingClient,
    SentenceTransformerEmbeddingClient,
)
from .errors import (
    LLMAllModelsFailedError,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from .redaction import redact_contact_details, redact_messages
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
    "DEFAULT_QUERY_TASK",
    "ChatMessage",
    "CircuitBreaker",
    "CompletionResult",
    "EmbeddingClient",
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
    "SentenceTransformerEmbeddingClient",
    "StreamChunk",
    "ToolCall",
    "ToolCallDelta",
    "ToolSchema",
    "redact_contact_details",
    "redact_messages",
]
