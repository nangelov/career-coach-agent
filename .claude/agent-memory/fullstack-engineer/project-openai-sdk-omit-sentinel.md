---
name: project-openai-sdk-omit-sentinel
description: openai SDK 2.x renamed the NOT_GIVEN sentinel to `omit`; chat.completions.create() type sigs require it under mypy --strict
metadata:
  type: project
---

The v2 LLM layer uses the `openai` async SDK (>=2.0) against HF Inference
Providers' OpenAI-compatible endpoint.

- **Use `from openai import omit`** for "omit this optional param" — NOT the old
  `NOT_GIVEN`. In openai 2.x, `create()` param types are `T | Omit` (e.g.
  `Optional[float] | Omit`); passing `NOT_GIVEN` fails `mypy --strict` with
  `incompatible type "... | NotGiven"; expected "... | Omit | None"`.
- **Overload resolution:** call `chat.completions.create(..., stream=False)` and
  `(..., stream=True)` with the **literal** bool at each call site so mypy picks
  the `ChatCompletion` vs `AsyncStream[ChatCompletionChunk]` overload. A runtime
  `bool` variable collapses the return to a union and breaks `async for`.
- **Message/tool param types** (`ChatCompletionMessageParam`,
  `ChatCompletionToolParam`, `ChatCompletionToolChoiceOptionParam`) are strict
  TypedDict unions — a plain `list[dict[str, Any]]` won't assign. Import them
  under `TYPE_CHECKING` and `cast("list[ChatCompletionMessageParam]", ...)`.
- **CI:** `openai` must be in the curated CI install (it's a light HTTP SDK, not
  ML) so both mypy sees real types and pytest can import the client — see
  [[project-uv-ci-heavy-deps]].
- **Tests:** inject an `httpx.AsyncClient(transport=httpx.MockTransport(...))`
  into `AsyncOpenAI(http_client=...)` to mock the wire with zero network. For
  streaming, return `text/event-stream` bytes of `data: {json}\n\n` chunks ending
  `data: [DONE]`. Set `max_retries=0` so a simulated timeout isn't retried 3x.
