# guardrails — input/output safety (jailbreak detection, PII scrub, policy)
#
# P4-08 landed the *minimal* input slice: a fast, deterministic deny-list heuristic
# (:func:`~app.guardrails.heuristics.screen_input`) wired into the graph's input-guardrail
# routing. SEC-02 adds the structural untrusted-content contract (design §7.3): the shared
# fencing helper (:func:`~app.guardrails.untrusted_content.fence_untrusted`) used wherever
# untrusted text meets a model, plus the deterministic output net
# (:func:`~app.guardrails.heuristics.screen_output`) that strips injection phrasing echoed back
# out of a response. The full jailbreak/injection classifier + PII scrubber are P10 — they
# replace ``screen_input`` / ``screen_output`` while keeping their ``SafetyVerdict`` contracts.
from app.guardrails.heuristics import (
    REFUSAL_MESSAGE,
    OutputScreenResult,
    screen_input,
    screen_output,
)
from app.guardrails.untrusted_content import fence_untrusted

__all__ = [
    "REFUSAL_MESSAGE",
    "OutputScreenResult",
    "fence_untrusted",
    "screen_input",
    "screen_output",
]
