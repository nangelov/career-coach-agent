---
name: feedback-aclosing-asynciterator
description: contextlib.aclosing() fails mypy on an AsyncIterator-typed value; use try/finally + getattr(stream, "aclose", None) for deterministic early-close of router streams
metadata:
  type: feedback
---

When you need **deterministic cleanup** of a streaming async generator on an early
return (e.g. cancel/stop mid-stream), do NOT wrap it in `contextlib.aclosing(...)` if
the value's declared type is `AsyncIterator[...]`. mypy `--strict` fails:
`Value of type variable "_SupportsAcloseT" of "aclosing" cannot be "AsyncIterator[...]"`
— `AsyncIterator` has no `aclose` in its type, and the concrete generator's `aclose`
is not visible through the declared return type.

**Why:** `LLMRouter.stream()` (and similar) declare `-> AsyncIterator[StreamChunk]`
(a locked public contract we don't widen). The runtime object is an async generator
*with* `aclose`, but the type says otherwise.
**How to apply:** manage the stream by hand and close best-effort in `finally`:
```python
stream = self._router.stream(...)
try:
    async for chunk in stream: ...
finally:
    aclose = getattr(stream, "aclose", None)
    if aclose is not None:
        await aclose()
```
`aclose` is a no-op on an already-exhausted stream, so this is safe on the normal
(non-cancel) path too. See [[feedback-redis-protocol-cast]] for the sibling
"don't widen the public seam, adapt at the boundary" pattern.
