---
name: project-next-route-handler-signature
description: Next.js App Router generated route types reject an optional first handler param — POST(request?: NextRequest) fails tsc
metadata:
  type: project
---

Next 15 generates `.next/types/app/api/**/route.ts` that type-check each Route Handler's
signature against `ParamCheck<Request | NextRequest>`. Making the first param **optional**
(`export async function POST(request?: NextRequest)`) fails `tsc --noEmit` with:
`Type 'NextRequest | undefined' is not assignable to type 'Request | NextRequest'`.

**How to apply:** always declare the first param non-optional — `POST(request: NextRequest)`.
If a handler needs to read the body defensively (e.g. the SEC-06 guest consent flag), keep the
param required and guard the parse instead:
```ts
let consent = false;
try { consent = ((await request.json()) as { consent?: unknown })?.consent === true; }
catch { consent = false; }
```
Unit tests that call the handler directly must then pass a real `NextRequest` (jsdom lacks
`Request`; use `@jest-environment node` — see [[bff-route-handlers]]).
