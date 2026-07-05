"""Provider-agnostic LLM exceptions.

The concrete client (``client.py``) translates provider SDK exceptions
(``openai.APITimeoutError`` etc.) into this small, stable hierarchy so callers —
above all the failover **router** (P1-02, §6.6) — can branch on *our* types
without importing the provider SDK.  The distinctions below map directly to the
router's failover / retry / circuit-breaker triggers.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every error raised by the LLM layer."""


class LLMTimeoutError(LLMError):
    """A per-call timeout (or first-token deadline) was exceeded.

    A primary failover trigger for the §6.6 router.
    """


class LLMConnectionError(LLMError):
    """The provider endpoint was unreachable (DNS / connection error)."""


class LLMResponseError(LLMError):
    """The provider returned a non-success HTTP status.

    ``status_code`` lets the router distinguish transient ``5xx`` (retry / fail
    over) from client ``4xx`` (do not retry).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMRateLimitError(LLMResponseError):
    """The provider rate-limited the request (HTTP 429).

    Distinct from a generic response error because free HF tiers rate-limit
    frequently and the router treats 429 as a failover/backoff trigger (§6.6).
    """

    def __init__(self, message: str, *, status_code: int | None = 429) -> None:
        super().__init__(message, status_code=status_code)


class LLMAllModelsFailedError(LLMError):
    """Every model in the failover router's ordered list failed or was skipped.

    Raised by the §6.6 router when no configured model could serve the request —
    either each one errored/timed out, or every model's circuit was open (all
    endpoints in cooldown). This is the router's terminal failure, distinct from
    the per-model errors above; the ``__cause__`` carries the last underlying
    :class:`LLMError` when one was seen.
    """
