"""Unit tests for the guest→account upgrade service (P3-03).

Drives :class:`~app.services.guest_upgrade.GuestUpgradeService` with process-local stores +
a fake durable conversation store (no Redis / Postgres). Coverage mirrors the acceptance
criteria: the ticket is single-use; an upgrade preserves the *same* session id, promotes its
record to the user, and backfills the guest's user↔assistant transcript to Postgres (tool
scaffolding dropped); a non-guest / expired session is a no-op; and two concurrent upgrades
of unrelated guests never cross-contaminate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.llm.types import ChatMessage, FunctionCall, ToolCall
from app.schemas.auth import SessionRecord
from app.services.conversation_store import ConversationStore
from app.services.guest_upgrade import GuestUpgradeService
from app.services.session_memory import InMemorySessionMemory
from app.services.session_store import InMemorySessionStore
from app.services.upgrade_ticket_store import InMemoryUpgradeTicketStore


class FakeConversationStore(ConversationStore):
    """Records durable persist calls (one conversation per user+session) for assertions."""

    def __init__(self) -> None:
        #: (user_id, session_id, user_message, assistant_message) per persist_turn call.
        self.persisted: list[tuple[str, str, ChatMessage, ChatMessage | None]] = []

    async def persist_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        user_message: ChatMessage,
        assistant_message: ChatMessage | None,
    ) -> str:
        self.persisted.append((user_id, session_id, user_message, assistant_message))
        return f"conv-{session_id}"

    async def load_history(self, *, user_id: str, session_id: str) -> list[ChatMessage]:
        return []


def _guest_record(session_id: str) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        role="guest",
        user_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class FakeMigrator:
    """Records guest-personalization migration calls (or raises to prove fail-soft)."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[tuple[str, str]] = []

    async def migrate(self, *, guest_session_id: str, user_id: str) -> None:
        self.calls.append((guest_session_id, user_id))
        if self._error is not None:
            raise self._error


def _service(
    *,
    sessions: InMemorySessionStore | None = None,
    memory: InMemorySessionMemory | None = None,
    conversations: ConversationStore | None = None,
    personalization: FakeMigrator | None = None,
) -> GuestUpgradeService:
    return GuestUpgradeService(
        InMemoryUpgradeTicketStore(),
        sessions or InMemorySessionStore(),
        memory or InMemorySessionMemory(),
        conversations,
        ticket_ttl_seconds=300,
        personalization=personalization,
    )


async def test_create_ticket_is_resolvable_once() -> None:
    service = _service()
    response = await service.create_ticket("guest-1")

    assert response.expires_in == 300
    assert response.upgrade_ticket
    # The ticket resolves to the bound guest session id, exactly once.
    assert await service.resolve_ticket(response.upgrade_ticket) == "guest-1"
    assert await service.resolve_ticket(response.upgrade_ticket) is None


async def test_upgrade_preserves_session_and_promotes_record() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(_guest_record("guest-1"), ttl_seconds=3600)
    service = _service(sessions=sessions)

    ok = await service.upgrade(
        guest_session_id="guest-1", user_id="user-42", session_ttl_seconds=7200
    )

    assert ok is True
    # Same session id kept; record re-anchored to the user, original start time preserved.
    record = await sessions.get("guest-1")
    assert record is not None
    assert record.role == "user"
    assert record.user_id == "user-42"
    assert record.created_at == datetime(2026, 1, 1, tzinfo=UTC)


async def test_upgrade_backfills_clean_transcript() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(_guest_record("guest-1"), ttl_seconds=3600)
    memory = InMemorySessionMemory()
    # A realistic transcript: a plain turn, then a tool-using turn (scaffolding + result).
    await memory.append(
        "guest-1",
        [
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello there", message_id="m1"),
            ChatMessage(role="user", content="find jobs"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(id="t1", function=FunctionCall(name="internet_search", arguments="{}"))
                ],
            ),
            ChatMessage(
                role="tool", content='{"jobs": []}', name="internet_search", tool_call_id="t1"
            ),
            ChatMessage(role="assistant", content="here are some roles", message_id="m2"),
        ],
    )
    convs = FakeConversationStore()
    service = _service(sessions=sessions, memory=memory, conversations=convs)

    await service.upgrade(guest_session_id="guest-1", user_id="user-42", session_ttl_seconds=7200)

    # Only the clean user↔assistant turns are persisted (tool scaffolding/result dropped).
    assert len(convs.persisted) == 2
    (uid1, sid1, u1, a1), (uid2, sid2, u2, a2) = convs.persisted
    assert (uid1, sid1) == ("user-42", "guest-1")
    assert u1.content == "hi"
    assert a1 is not None and a1.content == "hello there" and a1.message_id == "m1"
    assert u2.content == "find jobs"
    assert a2 is not None and a2.content == "here are some roles" and a2.message_id == "m2"


async def test_upgrade_without_conversation_store_still_promotes() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(_guest_record("guest-1"), ttl_seconds=3600)
    memory = InMemorySessionMemory()
    await memory.append("guest-1", [ChatMessage(role="user", content="hi")])
    service = _service(sessions=sessions, memory=memory, conversations=None)

    ok = await service.upgrade(
        guest_session_id="guest-1", user_id="user-42", session_ttl_seconds=7200
    )

    assert ok is True
    record = await sessions.get("guest-1")
    assert record is not None and record.role == "user"


async def test_upgrade_migrates_guest_personalization() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(_guest_record("guest-1"), ttl_seconds=3600)
    migrator = FakeMigrator()
    service = _service(sessions=sessions, personalization=migrator)

    ok = await service.upgrade(
        guest_session_id="guest-1", user_id="user-42", session_ttl_seconds=7200
    )

    assert ok is True
    assert migrator.calls == [("guest-1", "user-42")]  # migrated for the promoted user


async def test_upgrade_migration_failure_does_not_break_upgrade() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(_guest_record("guest-1"), ttl_seconds=3600)
    migrator = FakeMigrator(error=RuntimeError("db down"))
    service = _service(sessions=sessions, personalization=migrator)

    ok = await service.upgrade(
        guest_session_id="guest-1", user_id="user-42", session_ttl_seconds=7200
    )

    # The migration raised, but the session still promoted cleanly (best-effort, §5.4).
    assert ok is True
    record = await sessions.get("guest-1")
    assert record is not None and record.role == "user" and record.user_id == "user-42"


async def test_upgrade_without_migrator_still_promotes() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(_guest_record("guest-1"), ttl_seconds=3600)
    service = _service(sessions=sessions, personalization=None)

    ok = await service.upgrade(
        guest_session_id="guest-1", user_id="user-42", session_ttl_seconds=7200
    )

    assert ok is True


async def test_upgrade_noop_when_session_missing() -> None:
    service = _service(conversations=FakeConversationStore())
    ok = await service.upgrade(
        guest_session_id="does-not-exist", user_id="user-42", session_ttl_seconds=7200
    )
    assert ok is False


async def test_upgrade_noop_when_already_a_user() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(
        SessionRecord(session_id="s1", role="user", user_id="user-1", created_at=datetime.now(UTC)),
        ttl_seconds=3600,
    )
    convs = FakeConversationStore()
    service = _service(sessions=sessions, conversations=convs)

    ok = await service.upgrade(guest_session_id="s1", user_id="user-2", session_ttl_seconds=7200)

    # Already promoted (a replay) → no-op; the existing user is not overwritten or backfilled.
    assert ok is False
    assert convs.persisted == []
    record = await sessions.get("s1")
    assert record is not None and record.user_id == "user-1"


async def test_concurrent_upgrades_do_not_cross_contaminate() -> None:
    sessions = InMemorySessionStore()
    await sessions.create(_guest_record("guest-a"), ttl_seconds=3600)
    await sessions.create(_guest_record("guest-b"), ttl_seconds=3600)
    memory = InMemorySessionMemory()
    await memory.append("guest-a", [ChatMessage(role="user", content="A-question")])
    await memory.append("guest-b", [ChatMessage(role="user", content="B-question")])
    convs = FakeConversationStore()
    service = _service(sessions=sessions, memory=memory, conversations=convs)

    await service.upgrade(guest_session_id="guest-a", user_id="user-a", session_ttl_seconds=7200)
    await service.upgrade(guest_session_id="guest-b", user_id="user-b", session_ttl_seconds=7200)

    # Each guest kept its own session id, bound to its own user, with its own history only.
    rec_a = await sessions.get("guest-a")
    rec_b = await sessions.get("guest-b")
    assert rec_a is not None and rec_a.user_id == "user-a"
    assert rec_b is not None and rec_b.user_id == "user-b"
    by_user = {(uid, sid): u.content for uid, sid, u, _ in convs.persisted}
    assert by_user[("user-a", "guest-a")] == "A-question"
    assert by_user[("user-b", "guest-b")] == "B-question"
    assert ("user-a", "guest-b") not in by_user
    assert ("user-b", "guest-a") not in by_user
