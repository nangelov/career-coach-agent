"""Guest → account upgrade service (P3-03) — preserve the active session on login (§4).

When a guest completes SSO, the *same* active conversation must carry over to the newly
created/linked account rather than starting fresh (§4: *"Upgrade-to-account preserves
current session"*). This service owns that carry-over, kept out of
:class:`~app.services.auth.SsoAuthService` (which stays focused on the OIDC mechanics) and
depending only on **ports** so it touches no datastore driver directly (Router → Service →
Repository) and is unit-testable with fakes.

Two responsibilities:

* :meth:`create_ticket` — mint the short-lived, single-use upgrade ticket bound to a
  verified guest ``session_id`` (called by ``POST /api/auth/upgrade``).
* :meth:`resolve_ticket` / :meth:`upgrade` — consume that ticket and, on callback, promote
  the guest session **in place** to a logged-in one: keep the *same* ``session_id`` (so the
  live Redis conversation memory carries over untouched) while re-anchoring the session
  record to the user, and backfill the guest's prior transcript into Postgres so the
  conversation *begins persisting* like any logged-in session (§4).

Keeping the same ``session_id`` is the simplest correct carry-over: the Redis working
memory (``session:mem:<id>``) and the client's in-flight conversation both stay valid, so
after login the user lands back in the same conversation, not a blank one.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.config import Settings, settings
from app.llm.types import ChatMessage
from app.schemas.auth import SessionRecord, UpgradeTicketResponse
from app.services.conversation_store import ConversationStore
from app.services.session_memory import SessionMemory
from app.services.session_store import SessionStore
from app.services.upgrade_ticket_store import UpgradeTicketStore

logger = logging.getLogger(__name__)


def _pair_turns(
    messages: list[ChatMessage],
) -> list[tuple[ChatMessage, ChatMessage | None]]:
    """Reduce a live-session transcript to durable ``(user, assistant)`` turns.

    The Redis working memory holds the full transcript — user messages, the assistant's
    internal tool-call scaffolding, tool results, and the user-facing assistant answers.
    Postgres stores only the clean user↔assistant transcript (mirroring
    :meth:`~app.repositories.conversation_store.PostgresConversationStore.persist_turn`),
    so tool scaffolding/results are dropped here. A user message with no following answer
    (e.g. a turn cut off before content) is preserved with ``None`` so the question is not
    lost.
    """
    turns: list[tuple[ChatMessage, ChatMessage | None]] = []
    pending_user: ChatMessage | None = None
    for message in messages:
        if message.role == "user":
            if pending_user is not None:
                # Two user messages in a row (previous turn produced no answer).
                turns.append((pending_user, None))
            pending_user = message
        elif message.role == "assistant" and message.content:
            # A user-facing answer (tool-call scaffolding has no content and is skipped).
            if pending_user is not None:
                turns.append((pending_user, message))
                pending_user = None
    if pending_user is not None:
        turns.append((pending_user, None))
    return turns


class GuestUpgradeService:
    """Mint upgrade tickets and carry a guest's active session into a logged-in account.

    Ports (the ticket store, session store, session memory, and the optional durable
    conversation store) plus the ticket TTL are injected at construction (via
    :meth:`from_settings`), matching the sibling auth services — nothing reads the global
    ``settings`` in a method body.
    """

    def __init__(
        self,
        tickets: UpgradeTicketStore,
        sessions: SessionStore,
        memory: SessionMemory,
        conversations: ConversationStore | None,
        *,
        ticket_ttl_seconds: int,
    ) -> None:
        self._tickets = tickets
        self._sessions = sessions
        self._memory = memory
        self._conversations = conversations
        self._ticket_ttl_seconds = ticket_ttl_seconds

    @classmethod
    def from_settings(
        cls,
        tickets: UpgradeTicketStore,
        sessions: SessionStore,
        memory: SessionMemory,
        conversations: ConversationStore | None,
        config: Settings = settings,
    ) -> GuestUpgradeService:
        """Build from application config (upgrade-ticket TTL)."""
        return cls(
            tickets,
            sessions,
            memory,
            conversations,
            ticket_ttl_seconds=config.UPGRADE_TICKET_TTL_SECONDS,
        )

    async def create_ticket(self, guest_session_id: str) -> UpgradeTicketResponse:
        """Mint a short-lived, single-use ticket bound to ``guest_session_id``.

        Called by ``POST /api/auth/upgrade`` for a verified guest. The ticket id is an
        opaque ``uuid4().hex`` carrying no secret — it only names, server-side, which guest
        session a subsequent login is allowed to upgrade.
        """
        ticket = uuid4().hex
        await self._tickets.put(ticket, guest_session_id, ttl_seconds=self._ticket_ttl_seconds)
        return UpgradeTicketResponse(
            upgrade_ticket=ticket,
            expires_in=self._ticket_ttl_seconds,
        )

    async def resolve_ticket(self, ticket: str) -> str | None:
        """Consume ``ticket`` and return the guest session id it authorizes (single-use).

        Returns ``None`` for an unknown/expired/replayed ticket — the login then proceeds
        as a normal (non-upgrade) login rather than failing.
        """
        return await self._tickets.pop(ticket)

    async def upgrade(
        self,
        *,
        guest_session_id: str,
        user_id: str,
        session_ttl_seconds: int,
    ) -> bool:
        """Promote the guest session ``guest_session_id`` to belong to ``user_id``.

        Returns ``True`` when the carry-over happened (the caller then keeps the same
        ``session_id`` for the logged-in session), ``False`` when there was nothing to
        upgrade — the guest session expired, or it is not (any longer) a guest (already
        promoted / a replay) — in which case the caller mints a fresh session instead.

        Steps: (1) backfill the guest's prior user↔assistant transcript into Postgres so
        the conversation begins persisting like any logged-in session (best-effort — a DB
        failure must not block the login); (2) overwrite the session record **in place** as
        ``role="user"`` with ``user_id`` and the logged-in TTL, preserving the original
        ``created_at``. The Redis working memory is left untouched under the same key, so the
        live conversation continues seamlessly.
        """
        record = await self._sessions.get(guest_session_id)
        if record is None or record.role != "guest":
            return False

        await self._backfill(guest_session_id, user_id)

        # Re-anchor the session record to the user, keeping the same id (so the Redis
        # working memory and the client's conversation carry over) and its start time.
        await self._sessions.create(
            SessionRecord(
                session_id=guest_session_id,
                role="user",
                user_id=user_id,
                created_at=record.created_at,
            ),
            ttl_seconds=session_ttl_seconds,
        )
        logger.info("upgraded guest session %s to user", guest_session_id)
        return True

    async def _backfill(self, guest_session_id: str, user_id: str) -> None:
        """Persist the guest's prior transcript to Postgres (best-effort, per-turn).

        Reuses the durable store's :meth:`persist_turn` — the exact path a live logged-in
        turn takes — so backfilled history is byte-for-byte the same shape (get-or-create
        session + conversation, clean user↔assistant transcript). A persistence failure is
        logged and stops the backfill but never aborts the upgrade: the conversation still
        lives in Redis and future turns still persist. Guests without a durable store wired
        (no Postgres provider) simply skip this — the session still carries over.
        """
        if self._conversations is None:
            return
        transcript = await self._memory.load(guest_session_id)
        for user_message, assistant_message in _pair_turns(transcript):
            try:
                await self._conversations.persist_turn(
                    user_id=user_id,
                    session_id=guest_session_id,
                    conversation_id=None,
                    user_message=user_message,
                    assistant_message=assistant_message,
                )
            except Exception:  # noqa: BLE001 - backfill is best-effort; never block login
                logger.warning(
                    "failed to backfill guest history to Postgres (session=%s)",
                    guest_session_id,
                    exc_info=True,
                )
                return
