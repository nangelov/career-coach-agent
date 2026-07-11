---
name: project-guest-upgrade
description: Blessed P3-03 guest→account upgrade pattern — in-place same-session_id promotion + transcript backfill at upgrade boundary + server-minted single-use upgrade ticket
metadata:
  type: project
---

Blessed P3-03 (guest→account upgrade preserves session, §4, APPROVED rev 1).

**Rulings to hold consistent:**
- **Backfilling a guest's transcript AT the upgrade boundary is the sanctioned §4 reading**,
  NOT a "guests get persisted history" violation. The Redis-only rule ([[project-conversation-persistence]])
  ends the moment the account exists. Do not flag the upgrade backfill as a §4 breach.
- **In-place same-`session_id` promotion is the blessed carry-over** (not a re-key): `upgrade()`
  keeps the guest `session_id`, overwrites its `RedisSessionStore` record `guest→user` (+`user_id`,
  logged-in TTL, preserves `created_at`), leaves Redis working memory untouched. So the live
  conversation + client stay valid with zero data movement.
- **Backfill reuses `ConversationStore.persist_turn` (no port extension), best-effort, tool
  scaffolding dropped** — byte-identical shape to a live logged-in turn, consistent with P2-07
  lossy-durable ruling. DB failure logs + stops backfill but never blocks login.
- **Safe binding = server-minted opaque single-use upgrade ticket** (`UpgradeTicketStore` port in
  services/, `InMemory` fake, `RedisUpgradeTicketStore` adapter, prefix `upgrade:ticket`). `POST
  /api/auth/upgrade` is `require_auth` guest-only (else 409); ticket bound server-side to the
  VERIFIED guest session_id; consumed in `begin_login`, guest id stashed in the OAuth transaction
  (`OAuthStateRecord.upgrade_session_id`) — never a client-supplied guest id, never a token in URL.
- **`GuestUpgradeService` is a separate collaborator injected optionally into `SsoAuthService`** (SoC);
  `upgrade()==False` (lapsed guest session / replay / double-upgrade) → fresh session mint (graceful).

**Follow-up (noted, not gated):** future post-upgrade turns persisting depends on A10 (remove
client-trusted `ChatRequest.user_id`, derive from token) → P3-04. Backfill covers prior transcript
regardless. See [[project-auth-session-seam]].
