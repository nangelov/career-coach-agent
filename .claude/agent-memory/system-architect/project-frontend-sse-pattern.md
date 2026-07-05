---
name: project-frontend-sse-pattern
description: Blessed frontend §8 pattern (P1-08) — POST-SSE chat client in lib/, typed union mirroring backend schemas/chat.py, thin app/ page, UI in components/
metadata:
  type: project
---

**Blessed at P1-08 (frontend chat).** The canonical frontend layering for backend-talking features.

- **`frontend/lib/`** holds the transport/api-client seam (`chatStream.ts`): `fetch`+`ReadableStream`
  reader + a **pure stateful frame parser** (`push(chunk)→events[]`), injectable `fetchImpl` for tests.
  No React in lib.
- **`frontend/components/`** holds the UI (`Chat.tsx`, `"use client"`) — consumes the lib, no fetch/parse
  logic inside.
- **`frontend/app/`** route stays thin (renders the component).
- This lib/component/app split is the frontend analogue of the backend **Router→Service** rule — enforce it.

**Wire-contract rule:** the frontend event union MUST mirror `backend/app/schemas/chat.py` `ChatEvent`
field-for-field. Backend `_format_sse` serialises `data` with `exclude={"event"}`, so the parser
reconstructs the discriminator from the SSE `event:` line — verify frontend parsing against that, not
against a `data.event` field.

**Why:** POST-SSE cannot use GET-only `EventSource`; hand-rolled fetch+reader is the standing decision
(OSS/self-hosted, no paid SSE helper). Client-owned `session_id` (crypto.randomUUID) is the sanctioned
**P3 auth stand-in**; omitting `history` defers to server session memory (P1-05). Both are interim, not gaps.

**How to apply:** on future frontend tasks, require this same lib/component/app placement (§8) and demand
the typed union track the backend schema. See [[project-frontend-path]].
