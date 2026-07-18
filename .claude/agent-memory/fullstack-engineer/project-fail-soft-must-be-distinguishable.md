---
name: fail-soft-must-be-distinguishable
description: A fail-soft placeholder that passes downstream validation masks a real failure — give the caller an explicit signal
metadata:
  type: feedback
---

When an agent/function degrades gracefully on failure (LLM outage, unusable tool call) by
returning honest placeholder content instead of raising, that placeholder must be **distinguishable
from success** by the caller — otherwise it slips past downstream gates and gets persisted/returned
as if it were real output.

**Why:** In P7-03, `generate_pdp` returned six placeholder sentences on `LLMError` with `status`
left at `"ok"`. That placeholder (534 chars, 6 sections) passed `validate_pdp_content`, so the
service persisted a garbage `pdps` row and returned a 200 PDF; the `PdpGenerationFailed`/502 path
was unreachable for the most likely failure mode. Code-reviewer flagged it as a blocker.

**How to apply:** When adding a fail-soft path, carry an explicit failure signal (a distinct status
literal, a `None` return, a discriminated result) that the caller branches on — never rely on a
length/shape validator to catch a synthesis failure, because a well-formed placeholder passes it.
The safe-default value being *renderable* is fine; the safe-default being *indistinguishable from
success* is the bug. Also: a test that asserts the masked-success behavior (e.g. `status == "ok"`
after an outage) is encoding the bug — fix it at the root, don't preserve it.
