# guardrails — input/output safety (jailbreak detection, PII scrub, policy)
#
# The input gate (:func:`~app.guardrails.heuristics.screen_input`) is the real P10-01
# jailbreak/injection classifier behind a deny-list pre-filter; the untrusted-content contract
# (design §7.3) is the shared fencing helper
# (:func:`~app.guardrails.untrusted_content.fence_untrusted`) used wherever untrusted text meets
# a model. The output guardrail (:func:`~app.guardrails.heuristics.screen_output`, P10-03)
# redacts echoed injection, **system-prompt leakage**, and (opt-in, reusing the same P10-01
# classifier via :func:`~app.guardrails.heuristics.default_injection_classifier`) classifier-
# flagged segments from the final answer, keeping the ``SafetyVerdict`` / ``OutputScreenResult``
# contracts.
from app.guardrails.heuristics import (
    REFUSAL_MESSAGE,
    OutputScreenResult,
    default_injection_classifier,
    screen_input,
    screen_output,
)
from app.guardrails.untrusted_content import fence_untrusted

__all__ = [
    "REFUSAL_MESSAGE",
    "OutputScreenResult",
    "default_injection_classifier",
    "fence_untrusted",
    "screen_input",
    "screen_output",
]
