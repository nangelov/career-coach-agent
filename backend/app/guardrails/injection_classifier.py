"""In-process jailbreak / prompt-injection classifier (S8, design §7.4 / plan.md S8).

This is the **real** input-guardrail detector that replaces the P4 regex deny-list as the
actual gate (the deny-list stays only as a cheap fast-path pre-filter — see
:func:`app.guardrails.heuristics.screen_input`). It mirrors the ports-and-adapters shape the
embedding layer uses (:mod:`app.llm.embeddings`):

* :class:`InjectionClassifier` — the narrow **interface** ``screen_input`` depends on. It
  classifies a single message and returns an :class:`InjectionVerdict` — or ``None`` when the
  classifier is **unavailable**, an explicit fail-soft signal (not a benign-looking default)
  so the caller can decide the failure mode rather than silently trusting a fabricated
  "benign" result.
* :class:`PromptGuardClassifier` — the concrete adapter running a small HF ``Prompt-Guard``
  family model (``settings.INJECTION_CLASSIFIER_MODEL``, default
  ``meta-llama/Llama-Prompt-Guard-2-86M``) **in-process** via ``transformers`` — the same
  no-per-call-API-cost posture the in-process embeddings use (§6, budget/OSS-first §11). No
  paid inference dependency.

**Deployment prerequisite — gated default model.** The default
``meta-llama/Llama-Prompt-Guard-2-86M`` is a **gated** HF repo: the runtime needs an
``HF_TOKEN`` whose account has accepted the model licence, or the download fails. In a deploy
lacking that access the lazy load raises → the classifier latches *unavailable* → the input
gate falls back to the deny-list pre-filter (fail-open, see :func:`screen_input`). To avoid
that silent degradation either (a) provision a licence-accepted ``HF_TOKEN``, or (b) point
``INJECTION_CLASSIFIER_MODEL`` at an **ungated** equivalent (e.g. a
``protectai/deberta-*-prompt-injection`` model). Because the latched-unavailable state makes
the "real classifier" cosmetic, the load failure is logged at **ERROR** (not ``warning``) so a
misconfigured prod deploy surfaces in logs/alerting rather than passing silently.

**Long inputs are chunked, never dropped.** Prompt-Guard-family models have a 512-token
context, but ``ChatRequest.message`` allows up to 8000 chars (well over that). Feeding an
over-length string to the pipeline raises — which, under the fail-open policy, would let an
attacker *pad an injection past the context window to silently bypass the classifier*. Two
defences: the adapter (1) **splits** the message into ``chunk_chars``-sized windows and
classifies each, flagging if **any** window is malicious (the whole message is scanned, per
the model card's chunking guidance), and (2) builds the pipeline with ``truncation=True`` /
``max_length`` so even a pathological window is truncated rather than raising. The gate now
degrades gracefully on long input instead of failing open.

**Why the model is never loaded at import/construction time.** ``transformers`` (and the
``torch`` it needs for this model) are part of the heavy ML stack **excluded** from the
curated CI/dev install — a model download cannot run in CI or the sandbox. So the adapter
**lazy-loads** the pipeline on the first :meth:`~PromptGuardClassifier.classify` call, never
at import or ``__init__`` (exactly as the embedding client does). Importing this module and
constructing the classifier trigger **no** download.

**The pipeline build is behind an injectable seam** — the ``pipeline_factory`` constructor
arg: a zero-arg callable returning any object callable as ``pipeline(text) -> scores``.
Production leaves it defaulted (lazily builds the real ``transformers`` pipeline); tests
inject a small deterministic fake so no model is ever downloaded/run in CI or here.

**Fail-soft, latched.** If the pipeline cannot be built (library / model not available) or an
inference call raises, :meth:`~PromptGuardClassifier.classify` returns ``None`` and the
adapter latches "unavailable" so it does not retry a failing load on every turn. The *policy*
for an unavailable classifier (fail open vs. closed) lives in the caller,
:func:`app.guardrails.heuristics.screen_input`, which documents its choice.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

#: A zero-arg factory returning a ``transformers``-compatible text-classification pipeline —
#: an object callable as ``pipeline(text) -> scores`` (with ``top_k=None`` so every label's
#: score is returned). Injecting one is the test seam; the default builds the real pipeline
#: lazily.
PipelineFactory = Callable[[], Any]

#: Labels the Prompt-Guard family emits for a *benign* input (compared case-insensitively).
#: Any other top label is treated as malicious (prompt-injection / jailbreak). Prompt-Guard-2
#: is binary (benign vs. malicious, ``LABEL_0``/``LABEL_1``); the original Prompt-Guard used
#: named ``BENIGN``/``INJECTION``/``JAILBREAK`` labels — both are covered here.
_BENIGN_LABELS = frozenset({"benign", "label_0", "safe"})

#: Prompt-Guard-family context window (tokens). Used as the pipeline ``max_length`` truncation
#: bound so an over-length window is truncated rather than raising.
_MODEL_MAX_TOKENS = 512

#: Default character window a message is split into before classification. Conservatively below
#: ``_MODEL_MAX_TOKENS`` for typical text (~4 chars/token) so windows rarely need truncating;
#: ``truncation`` on the pipeline is the hard backstop for dense-token windows.
_DEFAULT_CHUNK_CHARS = 2000


@dataclass(frozen=True)
class InjectionVerdict:
    """One classification outcome: the top label, its malicious probability, and the decision.

    ``score`` is the malicious probability in ``[0, 1]``; ``flagged`` is ``score >= threshold``
    (the block decision). ``label`` is the top-scoring label, kept for internal telemetry only.
    """

    label: str
    score: float
    flagged: bool


class InjectionClassifier(ABC):
    """Interface :func:`app.guardrails.heuristics.screen_input` depends on — never a concrete
    model / SDK.

    :meth:`classify` returns an :class:`InjectionVerdict`, or ``None`` when the classifier is
    unavailable — an explicit signal so the caller picks the failure mode instead of a
    fabricated benign default masking a real outage.
    """

    @abstractmethod
    def classify(self, text: str) -> InjectionVerdict | None:
        """Classify ``text``; return the verdict, or ``None`` if the classifier is unavailable."""


class PromptGuardClassifier(InjectionClassifier):
    """:class:`InjectionClassifier` over an in-process ``transformers`` Prompt-Guard pipeline.

    The pipeline is **lazy-loaded** on first use (never at construction) and the build is
    injectable (:paramref:`pipeline_factory`) so CI/tests never download or run a real model —
    see the module docstring. On an unavailable model / library the classifier fails soft
    (returns ``None``) and latches, so it does not re-attempt a failing load every turn.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        threshold: float | None = None,
        chunk_chars: int = _DEFAULT_CHUNK_CHARS,
        pipeline_factory: PipelineFactory | None = None,
    ) -> None:
        """Construct the classifier without loading any model.

        Args:
            model_name: HF text-classification model id. Defaults to
                ``settings.INJECTION_CLASSIFIER_MODEL``.
            threshold: Malicious-probability block threshold (``>=``). Defaults to
                ``settings.INJECTION_CLASSIFIER_THRESHOLD``.
            chunk_chars: Character window a message is split into before classification, so
                inputs longer than the model's 512-token context are scanned window-by-window
                instead of raising (see the module docstring). Defaults to
                :data:`_DEFAULT_CHUNK_CHARS`.
            pipeline_factory: Zero-arg factory returning the classification backend (the
                injectable seam). ``None`` → the default lazily builds the real
                ``transformers`` pipeline on first use (its import is deferred to that call).
        """
        self._model_name = model_name or settings.INJECTION_CLASSIFIER_MODEL
        self._threshold = (
            settings.INJECTION_CLASSIFIER_THRESHOLD if threshold is None else threshold
        )
        self._chunk_chars = max(1, chunk_chars)
        self._pipeline_factory: PipelineFactory = pipeline_factory or self._build_default_pipeline
        # Lazily populated on first classify; guarded so concurrent first-callers load once.
        self._pipeline: Any | None = None
        self._unavailable = False
        self._load_lock = threading.Lock()

    def _build_default_pipeline(self) -> Any:
        """Build the real pipeline. Imported here so the ML stack is only needed on use.

        ``truncation`` / ``max_length`` are set so a window over the model's 512-token context
        is truncated rather than raising (the hard backstop behind character chunking).
        """
        from transformers import pipeline  # noqa: PLC0415 - deferred so import needs no ML stack

        return pipeline(
            "text-classification",
            model=self._model_name,
            top_k=None,
            truncation=True,
            max_length=_MODEL_MAX_TOKENS,
        )

    def _get_pipeline(self) -> Any | None:
        """Return the classification backend, building it once on first call.

        Returns ``None`` (and latches ``_unavailable``) if the build fails — e.g. the ML
        stack is not installed or the model cannot be downloaded — so callers can fail soft.
        """
        if self._pipeline is None and not self._unavailable:
            with self._load_lock:
                if self._pipeline is None and not self._unavailable:
                    try:
                        self._pipeline = self._pipeline_factory()
                    except Exception:
                        # Library/model unavailable (import error, download failure, …).
                        # Latch so we do not re-attempt a failing load on every turn.
                        self._unavailable = True
                        # ERROR, not warning: a latched-unavailable classifier makes the "real"
                        # input gate cosmetic (only the deny-list runs), so a misconfigured
                        # prod deploy — e.g. the gated default model without an accepted-licence
                        # HF_TOKEN — must surface loudly enough for alerting, not pass silently.
                        logger.error(
                            "Injection classifier unavailable (model=%s); input guardrail is now "
                            "degraded to the deny-list pre-filter only. Check the model is "
                            "downloadable (gated models need a licence-accepted HF_TOKEN).",
                            self._model_name,
                            exc_info=True,
                        )
        return self._pipeline

    def classify(self, text: str) -> InjectionVerdict | None:
        pipeline = self._get_pipeline()
        if pipeline is None:
            return None
        try:
            label, score = self._classify_windows(pipeline, text)
        except Exception:
            logger.warning("Injection classifier inference failed; failing soft.", exc_info=True)
            return None

        return InjectionVerdict(label=label, score=score, flagged=score >= self._threshold)

    def _classify_windows(self, pipeline: Any, text: str) -> tuple[str, float]:
        """Classify ``text`` window-by-window and return the **most malicious** ``(label, score)``.

        The message is split into :attr:`_chunk_chars`-sized windows so an injection padded
        beyond the model's 512-token context is still scanned (rather than raising and, under
        the fail-open policy, silently bypassing the gate — the C1 review finding). The window
        with the highest malicious probability wins, so any single malicious window flags the
        whole input.
        """
        top_label, top_score = "unknown", 0.0
        for window in _chunk(text, self._chunk_chars):
            label, score = _malicious_score(pipeline(window))
            if score >= top_score:
                top_label, top_score = label, score
        return top_label, top_score


def _chunk(text: str, size: int) -> list[str]:
    """Split ``text`` into consecutive windows of at most ``size`` characters (never empty)."""
    if len(text) <= size:
        return [text]
    return [text[i : i + size] for i in range(0, len(text), size)]


def _malicious_score(raw: Any) -> tuple[str, float]:
    """Reduce a ``transformers`` text-classification output to ``(top_label, malicious_prob)``.

    Handles the shapes a ``top_k=None`` pipeline emits for a single input: a ``list[dict]`` of
    ``{"label", "score"}`` (and the occasional extra-nested ``list[list[dict]]``). The
    malicious probability is the highest score among non-benign labels; if only a benign label
    was returned, it is inferred as the complement (``1 - benign``). The top label is the
    single highest-scoring entry (internal telemetry only).
    """
    scores = raw[0] if raw and isinstance(raw[0], list) else raw
    if not scores:
        return "unknown", 0.0

    benign_score = 0.0
    malicious_score = 0.0
    top_label = str(scores[0]["label"])
    top_score = float(scores[0]["score"])
    for item in scores:
        label = str(item["label"])
        value = float(item["score"])
        if value > top_score:
            top_label, top_score = label, value
        if label.lower() in _BENIGN_LABELS:
            benign_score += value
        else:
            malicious_score = max(malicious_score, value)

    # Only a benign label was returned (e.g. a top_k=1 benign result): infer the complement.
    if malicious_score == 0.0 and benign_score > 0.0:
        malicious_score = 1.0 - benign_score
    return top_label, malicious_score
