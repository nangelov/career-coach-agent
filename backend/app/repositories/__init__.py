# repositories — DB access layer (Postgres via SQLAlchemy + pgvector, Redis)

from .conversation_store import PostgresConversationStore
from .postgres import (
    Base,
    PostgresConnectionProvider,
    get_db_session,
    get_db_session_provider,
)
from .redis import (
    CancelRedis,
    RedisCancelRegistry,
    RedisConnectionProvider,
    RedisSessionMemory,
    SessionRedis,
)
from .vector_search import (
    MemorySearchResult,
    SearchResult,
    add_kb_chunk,
    add_user_memory,
    hybrid_search,
    hybrid_search_chunks,
    search_user_memories,
)

__all__ = [
    "Base",
    "CancelRedis",
    "MemorySearchResult",
    "PostgresConnectionProvider",
    "PostgresConversationStore",
    "RedisCancelRegistry",
    "RedisConnectionProvider",
    "RedisSessionMemory",
    "SearchResult",
    "SessionRedis",
    "add_kb_chunk",
    "add_user_memory",
    "get_db_session",
    "get_db_session_provider",
    "hybrid_search",
    "hybrid_search_chunks",
    "search_user_memories",
]
