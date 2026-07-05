"""Unit tests for the ``EmbeddingClient`` interface + its injectable-encoder seam (P2-06).

These never download or run the real ``Qwen/Qwen3-Embedding-8B`` model — that 8B model
cannot run in CI or the sandbox (``sentence-transformers``/``torch`` are excluded from the
curated install). Instead they exercise :class:`SentenceTransformerEmbeddingClient` through
its :paramref:`encoder_factory` seam with a small deterministic fake encoder, verifying:

* the model/encoder is **lazy** — never built at construction, built once on first embed;
* the query/document split applies the Qwen3 ``Instruct: ...\\nQuery:...`` prefix to queries
  only;
* outputs are coerced to plain ``list[list[float]]`` (works for numpy-like and list encoders).
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.llm.embeddings import (
    DEFAULT_QUERY_TASK,
    EmbeddingClient,
    SentenceTransformerEmbeddingClient,
)
from app.repositories.models.knowledge import EMBEDDING_DIM


class FakeEncoder:
    """A deterministic stand-in for ``SentenceTransformer`` — no model, no download.

    ``encode`` returns a hash-seeded :data:`EmbeddingClient.DIMENSION`-length vector per
    text and records the exact texts + kwargs it was called with, so tests can assert both
    the output shape and that the query instruction was applied.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append((list(texts), dict(kwargs)))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Tile the 32-byte digest out to DIMENSION deterministic floats in [0, 1).
        return [digest[i % len(digest)] / 255.0 for i in range(EmbeddingClient.DIMENSION)]


class CountingFactory:
    """Wraps a factory to count how many times it is invoked (proves lazy + once-only)."""

    def __init__(self) -> None:
        self.count = 0
        self.encoder = FakeEncoder()

    def __call__(self) -> FakeEncoder:
        self.count += 1
        return self.encoder


def test_dimension_is_locked_at_4096() -> None:
    assert EmbeddingClient.DIMENSION == 4096
    assert SentenceTransformerEmbeddingClient.DIMENSION == 4096


def test_embedding_dimension_matches_orm_vector_width() -> None:
    """The client's ``DIMENSION`` and the ORM's ``EMBEDDING_DIM`` (the ``vector(4096)``
    column width) are two independent constants (§6 item 3) — pin that they agree so a
    future coordinated dim migration cannot half-land. A test (not a cross-layer import)
    keeps the dependency direction correct: models must not import ``llm/``."""
    assert EmbeddingClient.DIMENSION == EMBEDDING_DIM


def test_construction_does_not_build_the_model() -> None:
    """Constructing the client must not invoke the encoder factory (no download at import)."""
    factory = CountingFactory()
    SentenceTransformerEmbeddingClient(encoder_factory=factory)
    assert factory.count == 0


async def test_embed_documents_shape_and_determinism() -> None:
    factory = CountingFactory()
    client = SentenceTransformerEmbeddingClient(encoder_factory=factory)

    vectors = await client.embed_documents(["alpha", "beta"])

    assert len(vectors) == 2
    assert all(len(v) == EmbeddingClient.DIMENSION for v in vectors)
    assert all(isinstance(value, float) for value in vectors[0])
    # Deterministic: same text → same vector.
    again = await client.embed_documents(["alpha"])
    assert again[0] == vectors[0]


async def test_empty_documents_returns_empty_without_loading() -> None:
    """An empty batch short-circuits — no encoder built, no encode call."""
    factory = CountingFactory()
    client = SentenceTransformerEmbeddingClient(encoder_factory=factory)

    assert await client.embed_documents([]) == []
    assert factory.count == 0


async def test_encoder_is_lazy_and_built_once() -> None:
    factory = CountingFactory()
    client = SentenceTransformerEmbeddingClient(encoder_factory=factory)

    assert factory.count == 0  # still not built after construction
    await client.embed_documents(["one"])
    await client.embed_query("two")
    await client.embed_documents(["three"])
    assert factory.count == 1  # built exactly once, then cached


async def test_embed_query_applies_instruction_prefix() -> None:
    factory = CountingFactory()
    client = SentenceTransformerEmbeddingClient(encoder_factory=factory)

    await client.embed_query("how do I switch to product management")

    encoded_texts, _kwargs = factory.encoder.calls[-1]
    assert encoded_texts == [
        f"Instruct: {DEFAULT_QUERY_TASK}\nQuery:how do I switch to product management"
    ]


async def test_embed_documents_have_no_instruction_prefix() -> None:
    factory = CountingFactory()
    client = SentenceTransformerEmbeddingClient(encoder_factory=factory)

    await client.embed_documents(["a plain document chunk"])

    encoded_texts, kwargs = factory.encoder.calls[-1]
    assert encoded_texts == ["a plain document chunk"]  # no "Instruct:" wrapping
    assert kwargs["normalize_embeddings"] is True


async def test_custom_query_task_is_used() -> None:
    factory = CountingFactory()
    client = SentenceTransformerEmbeddingClient(
        encoder_factory=factory, query_task="Retrieve career-coaching passages"
    )

    await client.embed_query("resume tips")

    encoded_texts, _ = factory.encoder.calls[-1]
    assert encoded_texts == ["Instruct: Retrieve career-coaching passages\nQuery:resume tips"]


async def test_numpy_like_output_is_coerced_to_float_lists() -> None:
    """An encoder returning an object with ``.tolist()`` (like numpy) is handled."""

    class NumpyLikeRow:
        def __init__(self, values: list[float]) -> None:
            self._values = values

        def tolist(self) -> list[list[float]]:
            return [self._values]

    class NumpyLikeEncoder:
        def encode(self, texts: list[str], **_kwargs: Any) -> NumpyLikeRow:
            return NumpyLikeRow([0.5] * EmbeddingClient.DIMENSION)

    client = SentenceTransformerEmbeddingClient(encoder_factory=NumpyLikeEncoder)
    vectors = await client.embed_documents(["x"])
    assert vectors == [[0.5] * EmbeddingClient.DIMENSION]
