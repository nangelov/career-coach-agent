---
name: frontend-lib-components-layering
description: Blessed Next.js frontend layering — lib/ = DOM-light DI API clients, components/ = React, app/ = routes
metadata:
  type: project
---

Blessed pattern for the v2 Next.js frontend (design §8, lines 377-383): `lib/` holds thin,
DOM-light API-client modules with injectable `fetchImpl`/`baseUrl` DI (mirrors the backend
Router→Service split); `components/` holds `"use client"` React view+state only; `app/`
holds App Router routes. New API surfaces must follow `lib/auth.ts` / `lib/chatStream.ts`:
wire TS types mirror backend Pydantic schemas **verbatim (snake_case)** so GET→edit→PUT
round-trips without a lossy remap, plus defensive `parse*` mappers.

**Why:** keeps transport unit-testable without DOM and matches the §8 structure block;
consistency across `lib/` modules is the accepted convention (P3/P5 frontend tasks).

**How to apply:** APPROVE frontend tasks that place transport in `lib/` (DI, no hard
`window`/`fetch` in pure paths) and React in `components/`; flag logic that puts fetch/status
mapping inside components or invents a non-wire field shape. Generic async-job polling belongs
in a reusable job-generic helper (backend `JobStatusResponse` is intentionally not CV-specific,
reused by P6 crawl/OCR). See [[frontend-guest-vs-user-contract]].
