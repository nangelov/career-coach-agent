# guardrails — input/output safety (jailbreak detection, PII scrub, policy)
#
# P4-08 lands the *minimal* input slice: a fast, deterministic deny-list heuristic
# (:mod:`app.guardrails.heuristics`) wired into the graph's input-guardrail routing. The
# full jailbreak/injection classifier, PII scrubber, and abuse/off-topic filter are P10 —
# they replace ``screen_input`` while keeping its ``SafetyVerdict`` contract.
from app.guardrails.heuristics import REFUSAL_MESSAGE, screen_input

__all__ = ["REFUSAL_MESSAGE", "screen_input"]
