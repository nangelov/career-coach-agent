---
name: project-abc-port-extension-breaks-fakes
description: Adding an abstractmethod to a ports-and-adapters ABC breaks every existing test fake/impl; prefer reusing existing methods
metadata:
  type: feedback
---

Adding a new `@abstractmethod` to a ports-and-adapters ABC (e.g. `ConversationStore`,
`SessionStore`, `SessionMemory`) breaks **every** existing implementation, including test
fakes scattered across `tests/` — they fail to instantiate until each grows the new method.

**Why:** this codebase has multiple fakes per port (e.g. `FakeConversationStore` /
`RaisingConversationStore` in `tests/test_chat_persistence.py`, plus in-memory prod doubles).
A silent break surfaces as abstract-instantiation TypeErrors far from the change.

**How to apply:** before extending a port, grep for its subclasses. Prefer composing new
behavior from the **existing** port methods in the calling service over adding an abstract
method. Concrete win (P3-03 guest upgrade): backfilled a guest transcript to Postgres by
looping the existing `ConversationStore.persist_turn` per user↔assistant turn — no port
change, no fake churn, and durable history stays byte-identical to the live-turn path
(DRY + KISS). Only add an abstractmethod when no existing method can express the need, and
then update all fakes in the same pass.
