"""In-process embedding client (``EmbeddingClient`` interface + implementation).

Design refs: app-design-and-features.md §6 item 3 (*"Embeddings →
``Qwen/Qwen3-Embedding-8B`` run **in-process via ``sentence-transformers``** (no API
cost), output dim **4096** → pgvector ``vector(4096)``"*) and §4 (the pgvector tables the
vectors this produces are written to / searched over).

This mirrors the ports-and-adapters shape the LLM layer already uses (``LLMClient`` in
``client.py``, ``SessionMemory`` / ``CancelRegistry`` in P1-05/06):

* :class:`EmbeddingClient` — the narrow **interface** every caller depends on. It exposes
  a batched document embedder and a single-text query embedder (the query/document split
  Qwen3 retrieval needs — see below) plus the fixed :data:`EmbeddingClient.DIMENSION`.
* :class:`SentenceTransformerEmbeddingClient` — the concrete adapter wrapping
  ``sentence_transformers.SentenceTransformer`` loaded with ``settings.EMBEDDING_MODEL``.

**Why the model is never loaded at import/construction time.** ``sentence-transformers``
and ``torch`` are deliberately **excluded** from the backend CI curated install (see
``.github/workflows/backend-ci.yml``) — a full 8B-param model cannot download or run in CI
or in the sandboxed dev environment. So the adapter **lazy-loads** the model: the
``SentenceTransformer`` is constructed only on the first ``embed_*`` call, never at import
or at ``__init__`` (exactly as ``HFOpenAICompatibleClient`` does not connect at
construction). Importing this module and constructing the client therefore trigger **no**
download.

**The encode step is behind an injectable seam** — the ``encoder_factory`` constructor arg:
a zero-arg callable returning any object with a ``sentence-transformers``-compatible
``.encode(list[str], normalize_embeddings=..., batch_size=...)`` method. Production leaves
it defaulted (lazily builds the real model); tests inject a small deterministic fake so no
8B model is ever downloaded/run in CI or here. This is the same "no live model in the
sandbox" posture prior tasks used for the "no live HF token" cases.

**Qwen3 query/document instruction split.** Per the ``Qwen/Qwen3-Embedding-8B`` model card,
*queries* should be wrapped as ``"Instruct: {task}\\nQuery:{text}"`` while *documents* get
**no** instruction (omitting the query instruct costs ~1-5% retrieval quality). Hence the
two methods: :meth:`~EmbeddingClient.embed_query` prepends the instruction,
:meth:`~EmbeddingClient.embed_documents` does not. The default task description
(:data:`DEFAULT_QUERY_TASK`) is the model card's generic-retrieval instruction; it is a
constructor arg so a retrieval scenario (e.g. the career KB) can tune it without a code
change — the exact wording is worth revisiting against the corpus before production tuning,
but it is **not** a blocker (the format itself is confirmed against the model card).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any

from app.config import settings

#: A zero-arg factory returning a ``sentence-transformers``-compatible encoder — the object
#: with ``.encode(list[str], normalize_embeddings: bool, batch_size: int)``. Injecting one
#: is the test seam; the default builds the real model lazily.
EncoderFactory = Callable[[], Any]

#: Default Qwen3 retrieval task description (model card generic-retrieval instruction). Only
#: applied to *queries*; tune per corpus via the constructor (see module docstring).
DEFAULT_QUERY_TASK = "Given a web search query, retrieve relevant passages that answer the query"


class EmbeddingClient(ABC):
    """Interface every embedding caller depends on — never a concrete model/SDK.

    One dimension for the whole system (:data:`DIMENSION` = 4096, §6 item 3), and a
    query/document split so callers request the right instruction handling for retrieval
    (see the module docstring). Implementations own model loading and the encode backend;
    callers depend only on these three members.

    ``embed_documents`` is the batched embedder (the ``embed(texts) -> list[list[float]]``
    shape the task calls for); ``embed_query`` is the single-text convenience that also
    applies the query instruction.
    """

    #: Fixed embedding width — the full (non-truncated) ``Qwen/Qwen3-Embedding-8B`` output
    #: (§6 item 3). Matches the ``vector(4096)`` columns in ``kb_chunks`` / ``user_memories``
    #: (P2-04). Locked: do not vary without a coordinated migration.
    DIMENSION: int = 4096

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` as *documents* (no query instruction).

        Returns one :data:`DIMENSION`-length vector per input, in order. An empty input
        returns an empty list without loading the model.
        """

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed ``text`` as a *query* (with the Qwen3 query instruction applied).

        Returns a single :data:`DIMENSION`-length vector.
        """


class SentenceTransformerEmbeddingClient(EmbeddingClient):
    """``EmbeddingClient`` over an in-process ``sentence-transformers`` model (§6 item 3).

    The model is **lazy-loaded** on first use (never at construction) and the encode backend
    is injectable (:paramref:`encoder_factory`) so CI/tests never download or run the real
    8B model — see the module docstring.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        encoder_factory: EncoderFactory | None = None,
        query_task: str = DEFAULT_QUERY_TASK,
        normalize_embeddings: bool = True,
        batch_size: int = 32,
    ) -> None:
        """Construct the client without loading any model.

        Args:
            model_name: ``sentence-transformers`` model id. Defaults to
                ``settings.EMBEDDING_MODEL`` (``Qwen/Qwen3-Embedding-8B``).
            encoder_factory: Zero-arg factory returning the encode backend (the injectable
                seam). ``None`` → the default lazily builds ``SentenceTransformer(model_name)``
                on first use (import of ``sentence_transformers`` is deferred to that call so
                importing this module needs no ML stack).
            query_task: Instruction task description prepended to *queries* only (see module
                docstring). Documents are embedded without an instruction.
            normalize_embeddings: L2-normalize outputs (recommended for cosine similarity —
                the pgvector search metric).
            batch_size: Encoder batch size for :meth:`embed_documents`.
        """
        self._model_name = model_name or settings.EMBEDDING_MODEL
        self._encoder_factory: EncoderFactory = encoder_factory or self._build_default_encoder
        self._query_task = query_task
        self._normalize = normalize_embeddings
        self._batch_size = batch_size
        # Lazily populated on first embed call; guarded so concurrent first-callers load once.
        self._encoder: Any | None = None
        self._load_lock = asyncio.Lock()

    def _build_default_encoder(self) -> Any:
        """Construct the real model. Imported here so the ML stack is only needed on use."""
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415 - deferred

        return SentenceTransformer(self._model_name)

    async def _get_encoder(self) -> Any:
        """Return the encode backend, building it once on first call (off the event loop)."""
        if self._encoder is None:
            async with self._load_lock:
                if self._encoder is None:
                    # Model construction is heavy/blocking — keep it off the event loop.
                    self._encoder = await asyncio.to_thread(self._encoder_factory)
        return self._encoder

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        encoder = await self._get_encoder()
        return await asyncio.to_thread(self._encode, encoder, list(texts))

    async def embed_query(self, text: str) -> list[float]:
        encoder = await self._get_encoder()
        instructed = f"Instruct: {self._query_task}\nQuery:{text}"
        vectors = await asyncio.to_thread(self._encode, encoder, [instructed])
        return vectors[0]

    def _encode(self, encoder: Any, texts: list[str]) -> list[list[float]]:
        """Run the (blocking) encoder and coerce its output to plain float lists.

        Accepts either a numpy array (``.tolist()``) or an already-nested sequence, so the
        real ``SentenceTransformer`` and a lightweight test fake both work.
        """
        raw = encoder.encode(
            texts,
            normalize_embeddings=self._normalize,
            batch_size=self._batch_size,
        )
        return _to_float_lists(raw)


def _to_float_lists(raw: Any) -> list[list[float]]:
    """Coerce an encoder output (numpy array or nested sequence) to ``list[list[float]]``."""
    tolist = getattr(raw, "tolist", None)
    if callable(tolist):
        raw = tolist()
    return [[float(value) for value in row] for row in raw]
