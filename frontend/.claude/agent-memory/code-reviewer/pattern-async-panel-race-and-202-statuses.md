---
name: pattern-async-panel-race-and-202-statuses
description: Two recurring FE checks for the market/roles + profile async surfaces — secondary-panel resubmit races and 202-vs-200 status mapping
metadata:
  type: project
---

Two checks that recur on the async market/profile surfaces (`lib/roles.ts`, `lib/profile.ts` + their components):

**1. Secondary-panel resubmit race.** These components run a two-step sequence in one handler:
resolve the primary payload (requirements), then a secondary one (gap). The busy flag that
disables the submit button is usually keyed only on the *primary* phase, so the button re-enables
while the *secondary* panel is still loading. The client fetch functions take only `baseUrl`/`fetchImpl`
(no `AbortSignal`) — only `pollJobUntilTerminal` honors the signal — so aborting on resubmit does NOT
cancel an in-flight secondary fetch, allowing a stale result to land after a new search starts.
**Why:** classic React async race, masked when the secondary panel only renders once the primary
phase is `ready`. **How to apply:** flag as minor unless the stale render is user-visible; suggest
disabling the button on the secondary phase too, or a per-submit generation token.

**2. 202-vs-200 status mapping.** The roles backend (`app/api/roles.py`) returns `role_profile_missing`
as a **202 mine handle** (poll path), NOT a 200 body — only `ok`/`profile_missing` come back at 200.
Before flagging a component's missing status branch as a bug, confirm which statuses actually reach the
200 body vs. the 202 poll loop. **How to apply:** an unhandled `role_profile_missing` in a 200-body
switch is a latent/defensive nit, not an active bug, given the current backend contract.
